#!/usr/bin/env python

import os
import sys
import json
import math
import argparse
import requests
import threading
import numpy as np
from itertools import product
from scipy.signal import argrelextrema
from datetime import datetime, date, timezone, timedelta
import seaborn as sns

from slack import WebClient
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]

from flask import Flask, render_template, request
app = Flask(__name__)

# courtesy of https://www.omnicalculator.com/other/latitude-longitude-distance
def deg2rad(deg):
    rad = deg * math.pi / 180.0
    return rad

def sphDist(lat1, long1, lat2, long2):
    r = 6371 * 1000
    dist = 2 * r * np.arcsin(
        math.sqrt(
            math.pow(
                np.sin((lat2 - lat1) / 2.0),
                2
            ) +
            np.cos(lat1) * np.cos(lat2) * math.pow(np.sin((long2 - long1) / 2.0),
                                                   2)
        )
    )
    return dist


def distance(l1, l2):
    res = sphDist(deg2rad(l1[0]), deg2rad(l1[1]), deg2rad(l2[0]), deg2rad(l2[1]))
    return res


class Schedule:
    def __init__(self, week, sat, sun):
        self.FMT = '%I:%M%p'

        self.week = self.parse_times(week)
        self.sat = self.parse_times(sat)
        self.sun = self.parse_times(sun)

        self.schedule = [[[x, []] for x in self.week],
                         [[x, []] for x in self.week],
                         [[x, []] for x in self.week],
                         [[x, []] for x in self.week],
                         [[x, []] for x in self.week],
                         [[x, []] for x in self.sat],
                         [[x, []] for x in self.sun]]
        self.schedule_sets = [0, 0, 0, 0, 0, 0,
                              0]  # if set - means the day has been passed - that's how we know the week passed and the value needs cleaning

        self.last_departure = datetime.now().time()

        self.cp = sns.color_palette("vlag",61).as_hex() # colorpalette

    def reset(self):
        self.schedule = [[[x, []] for x in self.week],
                         [[x, []] for x in self.week],
                         [[x, []] for x in self.week],
                         [[x, []] for x in self.week],
                         [[x, []] for x in self.week],
                         [[x, []] for x in self.sat],
                         [[x, []] for x in self.sun]]

    def get_today_json(self):
        # todo: when the bus is running late - compute the lateness here as the difference fcurrent time to scheduled time
        res = dict({"data": dict()})
        today_weekday = datetime.today().weekday()
        today_date = datetime.today().date()
        for v in self.schedule[today_weekday]:
            str_time = v[0].strftime("%H:%M")
            str_hr = v[0].strftime("%H")
            res["data"].setdefault(str_hr, [])

            if len(v[1]) == 0:
                res["data"][str_hr].append([str_time, "NA", '#b3b3b3'])
                continue

            # get closest value to the stop time
            idx = np.argmin(
                [abs(datetime.combine(today_date, x) - datetime.combine(today_date, v[0])).total_seconds() for x in
                 v[1]])
            closest = v[1][idx]
            closest_off = int(
                ((datetime.combine(today_date, closest) - datetime.combine(today_date, v[0])).total_seconds()) / 60)

            # set min max bounds
            if closest_off < 0:
                closest_off = max(-30, closest_off)
            if closest_off > 0:
                closest_off = min(30, closest_off)

            res["data"][str_hr].append([str_time, closest.strftime("%H:%M"), self.cp[closest_off + 30]])

        res["rows"] = list(res["data"])  # one row for each hour
        res["ncols"] = max([len(v) for k, v in res["data"].items()])

        return res

    def parse_times(self, tms):
        res = []
        for x in tms:
            st = datetime.strptime(x, self.FMT)
            tst = datetime.time(st)
            res.append(tst)

        return sorted(res)

    # colors - blue to red (black when not yet available) - blue means departed early - red means departed late
    def add_departure(self, vid, timestamp):
        # what if we simply assign the same departure to multiple stops? and then report the one which minimizes absolute difference?

        # departure is observed
        # does the last stop before the departure have a departure associated with it?
        # assign to both previous and next stop
        tm = datetime.fromtimestamp(timestamp / 1000)
        depart_weekday = tm.weekday()
        depart_date = tm.date()
        depart_time = tm.time()
        self.last_departure = depart_time

        found_stop = False
        next_idx = None

        tomorrow_weekday = (depart_weekday + 1) % 7
        if self.schedule_sets[tomorrow_weekday] == 1:  # reset
            self.schedule_sets[tomorrow_weekday] = 0
            tmp = [x[0] for x in self.schedule[tomorrow_weekday]]
            self.schedule[tomorrow_weekday] = [[x, []] for x in tmp]

        # set todays data as being written
        self.schedule_sets[depart_weekday] = 1

        for i in range(len(self.schedule[depart_weekday])):
            stop_time = datetime.combine(depart_date, self.schedule[depart_weekday][i][0])
            td = (tm - stop_time).total_seconds()
            if td < 0:  # found the next stop
                found_stop = True
                # add to the next stop
                self.schedule[depart_weekday][i][1].append(depart_time)
            if i > 0:
                self.schedule[depart_weekday][i - 1][1].append(depart_time)

            if found_stop:
                next_idx = i
                break

        # if the first of the day - i==0 - need to add to the previous days last stop
        if next_idx == 0:
            yesterday_weekday = (depart_weekday - 1) % 7
            self.schedule[yesterday_weekday][-1][1].append(depart_time)

        # if the last of the day - need to add to the next days first stop
        if next_idx is None:
            tomorrow_weekday = (depart_weekday + 1) % 7
            self.schedule[tomorrow_weekday][0][1].append(depart_time)

        return

    def get_late(self):
        res = []
        cnow = datetime.now()
        cdate = cnow.date()
        ctime = cnow.time()
        weekday = cnow.weekday()
        for s in self.schedule[weekday]:
            if s[
                0] < self.last_departure:  # not interested anymore - values will not update anymore since before the latest departure
                continue
            if s[0] > ctime:  # found stop after the current time - no need to look further
                break

            stop_time = datetime.combine(cdate, s[0])
            td = (cnow - stop_time).total_seconds()

            res.append([s[0], abs(td)])

        # todo: report negative when departed earlier
        # todo: only report if >n minutes late

        return res


class Vehicle:
    def __init__(self, vid, route_id):
        self.vid = vid
        self.route_id = route_id
        self.travel = []

    def update(self, timestamp, position):
        if len(self.travel) == 0 or timestamp > self.travel[-1][0]:
            self.travel.append((timestamp, position))
            return True
        return False

    def reset(self):
        self.travel = list()

    def get_id(self):
        return self.vid


class Stop:
    def __init__(self, id, code, name, position):
        self.id = id
        self.code = code
        self.name = name
        self.position = position
        self.schedule = None
        self.observed_departures = list()
        self.v_distances = dict()

        self.last_stop = 0  # indicates the index of the last stop from the schedule which occurred

    def update(self, vid, timestamp, vpos):
        self.v_distances.setdefault(vid, [[], []])
        self.v_distances[vid][0].append(timestamp)
        self.v_distances[vid][1].append(distance(vpos, self.position))

        return self.v_distances[vid][1][-1]

    def time_diff(self, t1, t2, min_diff=0):  # returns true if two values differ by more min_diff number of seconds
        return

    def depart(self,
               vid,  # vehicle ID
               order_n,  #
               min_dist_to_stop,
               min_dist_between_stops,
               min_time_between_stops,
               stop_radius):  # returns 0 if no new departure detected - returns 1 if there is departure
        assert vid in self.v_distances, "requested vehicle is not available"

        # find local minima etc
        tmp_indices_1 = argrelextrema(np.array(self.v_distances[vid][1]), np.less_equal, order=order_n)[0]  # todo: replace container list with np.array to avoid conversions
        # select all that are also closer than min distance
        tmp_indices_2 = [c for c in tmp_indices_1 if self.v_distances[vid][1][c] < min_dist_to_stop]

        # remove duplicates close in time
        close_dist_indices = []
        for ci in tmp_indices_2:
            if any(abs(self.v_distances[vid][0][ci] - timestamp_b) < min_time_between_stops for timestamp_b in
                   self.v_distances[vid][0][:ci]):
                continue
            close_dist_indices.append(ci)

        # make sure appropriate distance has been travelled or that the bus departed if the first in the day
        indices = []
        found_stop = 0
        prev_idx = 0
        trim_to_idx = 0  # index to which the observations are to be trimmed if stops found
        for i, c in enumerate(close_dist_indices):
            if i == len(close_dist_indices) - 1:  # last one
                remaining_dists = self.v_distances[vid][1][c:]
                if len(remaining_dists) > 0 and max(
                        remaining_dists) > min_dist_to_stop:  # departed from last observation
                    indices.append(c)
                    found_stop = 1
                    trim_to_idx = len(self.v_distances[vid][1])
            else:
                sub_dists = self.v_distances[vid][1][c:close_dist_indices[i + 1]]  # distance between current and next index
                if len(sub_dists) > 0 and max(sub_dists) >= min_dist_between_stops:
                    indices.append(c)
                    prev_idx = c
                    found_stop = 1
                    trim_to_idx = close_dist_indices[i + 1]

        # print("f1: "+str(len(tmp_indices_1)))
        # print(list(self.v_distances))
        # print(len(self.v_distances[vid]))
        # print(len(self.v_distances[vid][1]))
        # print("f2: "+str(len(tmp_indices_2)))
        # print("f3: "+str(len(close_dist_indices)))
        # print("f4: "+str(len(indices)))

        departures = []
        for c in indices:
            # find the first index for which position is greater than radius
            npl = self.v_distances[vid][1][c:]
            cur_radius = npl[0] + stop_radius  # minimum plus radius
            radius_idx = np.argmax(npl > cur_radius)
            if radius_idx > 0:
                radius_idx -= 1  # we want index within radius not outside

            self.observed_departures.append(self.v_distances[vid][0][c + radius_idx])
            departures.append([datetime.fromtimestamp(self.v_distances[vid][0][c + radius_idx] / 1000).strftime("%c"),
                               self.v_distances[vid][1][c + radius_idx]])
            # if a departure was found - update timetable
            if self.schedule is None:
                print("schedule is now None")
            self.schedule.add_departure(vid, self.v_distances[vid][0][c + radius_idx])

        # lastly, clean up distances up until this departure to prepare for the next round
        if found_stop:
            self.v_distances[vid][0] = self.v_distances[vid][0][trim_to_idx:]
            self.v_distances[vid][1] = self.v_distances[vid][1][trim_to_idx:]

        # if departure is found - record it and remove the vehicle record up to this point
        return departures

    def get_delta(self, t1, t2):
        ct1 = datetime.combine(date.today(), t1)
        ct2 = datetime.combine(date.today(), t2)
        td = (ct1 - ct2).total_seconds()
        return td

    def _closest(self, l1, l2, res, max_delta, recycle=False, future_only=False):
        if len(l1) == 0 or len(l2) == 0:
            return res
        p = None
        if not future_only:
            p = product(l1, l2)
        else:
            p = [x for x in list(product(l1, l2)) if x[0] <= x[1]]
            if len(p) == 0:
                return res

        cl = min(p, key=lambda t: abs(self.get_delta(t[0], t[1])))
        if abs(self.get_delta(cl[0], cl[1])) > max_delta:
            for x in l1:
                res.append((x, 0))
            return res

        else:
            res.append(cl)
            t1 = [x for x in l1]
            t1.remove(cl[0])
            t2 = [x for x in l2]
            if not recycle:
                t2.remove(cl[1])
            self._closest(t1, t2, res, max_delta, recycle, future_only)

    def reset(self):
        # cleanup inactive vehicles
        to_clean = []
        reset_idxs = []
        yesterday_date = datetime.today() - timedelta(days=1)
        yesterday_midnight = datetime.combine(yesterday_date, datetime.min.time())
        cur_time = datetime.now()
        for vid, data in self.v_distances.items():
            # find inactive buses
            td = abs((datetime.fromtimestamp(data[0][-1] / 1000) - cur_time).total_seconds())
            if td > 3600:  # inacetive for over 1hr
                to_clean.append(vid)
                continue

            # reset to before yesterdays midnight
            prev_day_idx = None
            for i, v in enumerate(data[0]):
                if datetime.fromtimestamp(v/1000) - yesterday_midnight < 0:  # value is before yesterdays midnight
                    prev_day_idx = i
                else:
                    break
            if prev_day_idx is not None:
                reset_idxs.append([vid, i])

        # cleanup inactive busses
        for vid in to_clean:
            del self.v_distances[vid]

        # reset old
        for vid, i in reset_idxs:
            self.v_distances[vid][0] = self.v_distances[vid][0][i]
            self.v_distances[vid][1] = self.v_distances[vid][1][i]
        # todo: same for self.departures

    def get_late(self):
        return self.schedule.get_late()

    def set_schedule(self, week, sat, sun):
        self.schedule = Schedule(week, sat, sun)

    def get_position(self):
        return self.position

    def get_code(self):
        return self.code

    def get_name(self):
        return self.name

    def get_today_json(self):
        return self.schedule.get_today_json()


class Collector:
    def __init__(self, setup_fname, outdir):
        self.setup_fname = setup_fname
        self.route_long_name = None
        self.route_id = None
        self.last_update_time = datetime.now()
        self.vehicles = dict()
        self.stops = dict()
        self.stop_names = list()

        self.order_n = 100
        self.min_dist_to_stop = sys.maxsize
        self.min_dist_between_stops = 0
        self.min_time_between_stops = 0
        self.stop_radius = 0
        self.late_time = 5

        self.slack_client = None
        self.slack_channel = None

        # initialize output files
        self.outdir = outdir.rstrip("/") + "/"
        if not os.path.exists(self.outdir):
            os.mkdir(self.outdir)

        self.log_date = date.today()
        self.log_all_fname = None
        self.log_all_fp = None

        # LOGIC
        self.setup()
        self.init_logs()

        self.observed_late = dict()  # stores times fow which lateness is bein collected - this way we can quickly when an update is required based on the requested number of minutes

    def set_min_distance_to_stop(self, min_distance_to_stop):
        self.min_dist_to_stop = min_distance_to_stop

    def set_min_distance_between_stops(self, min_dist_between_stops):
        self.min_dist_between_stops = min_dist_between_stops

    def set_min_time_between_stops(self, min_time_between_stops):
        self.min_time_between_stops = min_time_between_stops

    def set_stop_radius(self, stop_radius):
        self.stop_radius = stop_radius

    def set_order(self, order):
        self.order_n = order

    def set_late_time(self, late_time):
        self.late_time = late_time

    def set_slack(self, sc, channel):
        self.slack_client = sc
        self.slack_channel = channel

    def init_logs(self):
        if self.log_all_fp is not None:
            self.log_all_fp.close()
        cur_date = datetime.now().strftime("%Y%m%d")
        self.log_all_fname = self.outdir + "log.all." + cur_date + ".csv"
        if os.path.exists(self.log_all_fname):
            print("new log file already exists - overwriting: " + self.log_all_fname)

        self.log_all_fp = open(self.log_all_fname, "w+")

    def reset(self):
        for sid, s in self.stops.items():
            s.reset()
        for vid, v in self.vehicles.items():
            v.reset()

        self.init_logs()

    def collect_late(self):
        res = {}

        for sid, s in self.stops.items():
            sres = s.get_late()
            res[sid] = sres

        return res

    def get_today_json(self):
        res = dict({"stops":[],
                    "stop_data":dict()})
        for sid in list(self.stops):
            res["stops"].append(self.stops[sid].get_name())
            res["stop_data"][self.stops[sid].get_name()] = self.stops[sid].get_today_json()

        return res

    def _collecting(self, lock):
        threading.Timer(1.0, self._collecting, [lock]).start()

        # check if day passed - if did - reset
        midnight = datetime.combine(date.today(), datetime.min.time())  # midnight
        cur_time = datetime.combine(midnight.date(),
                                    datetime.now().time())  # by removing date from now and adding one from midnight - we ensure they are the same
        time_delta = (cur_time - midnight).total_seconds()

        if self.log_date != date.today():  # trigger resets and cleanup of old data
            self.log_date = date.today()
            res = self.reset()

        url = "https://feeds.transloc.com/3/vehicle_statuses?agencies=641&include_arrivals=true"
        payload = {}
        headers = {}
        response = ""
        try:
            response = requests.request("GET", url, headers=headers, data=payload)
        except:
            print("failed to get status at: " + datetime.today().strftime("%c"))
            return

        output = response.json()

        if output["success"] is not True:
            exit(1)

        # for each stop we can now check which buses crossed it and estimate time at which the stop occurred
        for v in output["vehicles"]:
            # check that the vehicle belongs to the correct route
            if not v["route_id"] == self.route_id:
                continue

            # update vehicle positioning if changed
            self.vehicles.setdefault(v["id"], Vehicle(v["id"], v["route_id"]))
            updated = self.vehicles[v["id"]].update(v["timestamp"], v["position"])

            if updated:
                for sid in self.stops:
                    stop_dist = self.stops[sid].update(v["id"], v["timestamp"], v["position"])
                    departures = self.stops[sid].depart(v["id"], self.order_n, self.min_dist_to_stop,
                                                        self.min_dist_between_stops, self.min_time_between_stops,
                                                        self.stop_radius)  # check if departed - if did mark and edit accordingly - resets the vehicle history for the stop and for the vehicle

                    stop_departed = 0
                    for d in departures:
                        # remove lateness before the current departure
                        self.observed_late = {k: v for k, v in self.observed_late.items() if
                                              not (k[0] == sid and k[1] < datetime.fromtimestamp(d[1]).time())}

                        stop_departed = 1
                        message = "{0} : {1} departed at {2} ({3})".format(self.stops[sid].get_name(), v["id"], d[0],
                                                                           d[1])
                        print(message)
                        try:
                            result = self.slack_client.chat_postMessage(
                                channel=self.slack_channel,
                                text=message
                            )

                        except:
                            print("error posting to slack: " + message)

                    with lock:
                        out_line = str(sid) + "," + str(v["id"]) + "," + str(v["timestamp"]) + "," + str(
                            stop_dist) + "," + str(stop_departed) + "\n"
                        self.log_all_fp.write(out_line)

        # collect lateness info
        # since it's being collected independent of departures
        # it can detect when something is behind schedule before a new departure occurs
        lateness = self.collect_late()
        for sid, lv in lateness.items():
            for l in lv:
                self.observed_late.setdefault((sid, l[0]), self.late_time)
                # check whether it is time to report lateness
                if l[1] >= self.observed_late[(sid, l[0])] * 60:
                    self.observed_late[(sid, l[0])] += self.late_time  # increment for the next time

                    hrs = int(l[1] // 3600)
                    mns = int((l[1] % 3600) // 60)
                    sec = int(l[1] % 60)
                    late_message = "{0} : {1} has not yet departed ({2}:{3}:{4}))".format(self.stops[sid].get_name(),
                                                                                          str(l[0]), str(hrs), str(mns),
                                                                                          str(sec))
                    print(late_message)
                    try:
                        result = self.slack_client.chat_postMessage(
                            channel=self.slack_channel,
                            text=late_message
                        )

                    except:
                        print("error posting to slack: " + late_message)

    def start_collecting(self):
        lock = threading.Lock()
        self._collecting(lock)

    def setup(self):
        assert os.path.exists(self.setup_fname), "setup file does not exist: " + self.setup_fname
        with open(self.setup_fname, "r") as inFP:
            for line in inFP:
                if line[0] == "#":  # header line
                    continue

                lcs = line.strip().split(",")
                assert len(
                    lcs) == 5, "incorrect number of columns in the setup file. Expected the following format: route_long_name,stop,week,sat,sun"

                # ROUTE
                if self.route_long_name is None:
                    self.route_long_name = lcs[0]
                    self.init_route()
                else:
                    assert self.route_long_name == lcs[
                        0], "multiple routes are not supported at this time. Please ensure your setup file has a single route name specified in the first column"

                # STOP
                sid = self.init_stop(lcs[1])
                self.stops[sid].set_schedule(lcs[2].split(";"), lcs[3].split(";"), lcs[4].split(";"))

    def init_stop(self, stop_name):

        # now get stops using the route ID
        url = "https://feeds.transloc.com/3/stops?agencies=641&include_routes=true"
        payload = {}
        headers = {}
        response = requests.request("GET", url, headers=headers, data=payload)

        output = response.json()

        rcv_routes = {r["id"]: r for r in output["routes"]}
        rcv_stops = {s["id"]: s for s in output["stops"]}

        found_stop = False
        stop_sid = None
        for rid, r in rcv_routes.items():
            if r["id"] == self.route_id:
                for s in r["stops"]:
                    if rcv_stops[s]["name"] != stop_name:
                        continue
                    else:
                        self.stops[s] = None
                        found_stop = True
                        stop_sid = s
                        break

        assert found_stop, "didn't find requested stop: " + stop_name

        # lastly add additional information about the stops
        for sid, s in rcv_stops.items():
            if s["id"] == stop_sid:
                self.stops[s["id"]] = Stop(s["id"], s["code"], s["name"], s["position"])

        return stop_sid

    def init_route(self):
        url = "https://feeds.transloc.com/3/routes?agencies=641&include_arrivals=true"
        payload = {}
        headers = {}
        response = requests.request("GET", url, headers=headers, data=payload)

        output = response.json()
        assert output["success"] is True, "unsuccessful attempt at getting routes"
        assert "routes" in output, "incorrect response: " + output

        found_route = False
        for r in output["routes"]:
            if r["long_name"] == self.route_long_name:
                found_route = True
                self.route_id = r["id"]

        assert found_route, "requested route was not found"

collector = None

def generator():
    global collector
    hrs = {'data': {'00': [['00:00', 'NA', '#b3b3b3'], ['00:30', 'NA', '#b3b3b3']], '06': [['06:00', 'NA', '#b3b3b3'], ['06:15', 'NA', '#b3b3b3'], ['06:30', 'NA', '#b3b3b3'], ['06:45', 'NA', '#b3b3b3']], '07': [['07:00', 'NA', '#b3b3b3'], ['07:15', 'NA', '#b3b3b3'], ['07:30', 'NA', '#b3b3b3'], ['07:36', 'NA', '#b3b3b3'], ['07:42', 'NA', '#b3b3b3'], ['07:48', 'NA', '#b3b3b3'], ['07:54', 'NA', '#b3b3b3']], '08': [['08:00', 'NA', '#b3b3b3'], ['08:06', 'NA', '#b3b3b3'], ['08:12', 'NA', '#b3b3b3'], ['08:18', 'NA', '#b3b3b3'], ['08:24', 'NA', '#b3b3b3'], ['08:30', 'NA', '#b3b3b3'], ['08:36', 'NA', '#b3b3b3'], ['08:42', 'NA', '#b3b3b3'], ['08:48', 'NA', '#b3b3b3'], ['08:54', 'NA', '#b3b3b3']], '09': [['09:00', 'NA', '#b3b3b3'], ['09:10', 'NA', '#b3b3b3'], ['09:20', 'NA', '#b3b3b3'], ['09:30', 'NA', '#b3b3b3'], ['09:40', 'NA', '#b3b3b3'], ['09:50', 'NA', '#b3b3b3']], '10': [['10:00', 'NA', '#b3b3b3'], ['10:15', 'NA', '#b3b3b3'], ['10:30', 'NA', '#b3b3b3'], ['10:45', 'NA', '#b3b3b3']], '11': [['11:00', 'NA', '#b3b3b3'], ['11:15', 'NA', '#b3b3b3'], ['11:30', 'NA', '#b3b3b3'], ['11:45', 'NA', '#b3b3b3']], '12': [['12:00', 'NA', '#b3b3b3'], ['12:15', 'NA', '#b3b3b3'], ['12:30', 'NA', '#b3b3b3'], ['12:45', 'NA', '#b3b3b3']], '13': [['13:00', 'NA', '#b3b3b3'], ['13:15', 'NA', '#b3b3b3'], ['13:30', 'NA', '#b3b3b3'], ['13:45', 'NA', '#b3b3b3']], '14': [['14:00', 'NA', '#b3b3b3'], ['14:15', 'NA', '#b3b3b3'], ['14:30', 'NA', '#b3b3b3'], ['14:45', 'NA', '#b3b3b3']], '15': [['15:00', 'NA', '#b3b3b3'], ['15:06', 'NA', '#b3b3b3'], ['15:12', 'NA', '#b3b3b3'], ['15:18', 'NA', '#b3b3b3'], ['15:24', 'NA', '#b3b3b3'], ['15:30', 'NA', '#b3b3b3'], ['15:36', 'NA', '#b3b3b3'], ['15:42', 'NA', '#b3b3b3'], ['15:48', 'NA', '#b3b3b3'], ['15:54', 'NA', '#b3b3b3']], '16': [['16:00', 'NA', '#b3b3b3'], ['16:06', 'NA', '#b3b3b3'], ['16:12', 'NA', '#b3b3b3'], ['16:18', 'NA', '#b3b3b3'], ['16:24', 'NA', '#b3b3b3'], ['16:30', 'NA', '#b3b3b3'], ['16:36', 'NA', '#b3b3b3'], ['16:42', 'NA', '#b3b3b3'], ['16:48', 'NA', '#b3b3b3'], ['16:54', 'NA', '#b3b3b3']], '17': [['17:00', 'NA', '#b3b3b3'], ['17:06', 'NA', '#b3b3b3'], ['17:12', 'NA', '#b3b3b3'], ['17:18', 'NA', '#b3b3b3'], ['17:24', 'NA', '#b3b3b3'], ['17:30', 'NA', '#b3b3b3'], ['17:36', 'NA', '#b3b3b3'], ['17:42', 'NA', '#b3b3b3'], ['17:48', 'NA', '#b3b3b3'], ['17:54', 'NA', '#b3b3b3']], '18': [['18:00', 'NA', '#b3b3b3'], ['18:10', 'NA', '#b3b3b3'], ['18:20', 'NA', '#b3b3b3'], ['18:30', 'NA', '#b3b3b3'], ['18:45', 'NA', '#b3b3b3']], '19': [['19:00', 'NA', '#b3b3b3'], ['19:15', 'NA', '#b3b3b3'], ['19:30', 'NA', '#b3b3b3'], ['19:45', 'NA', '#b3b3b3']], '20': [['20:00', 'NA', '#b3b3b3'], ['20:15', 'NA', '#b3b3b3'], ['20:30', 'NA', '#b3b3b3']], '21': [['21:00', 'NA', '#b3b3b3'], ['21:30', 'NA', '#b3b3b3']], '22': [['22:00', 'NA', '#b3b3b3'], ['22:30', 'NA', '#b3b3b3']], '23': [['23:00', 'NA', '#b3b3b3'], ['23:30', 'NA', '#b3b3b3']]}, 'rows': ['00', '06', '07', '08', '09', '10', '11', '12', '13', '14', '15', '16', '17', '18', '19', '20', '21', '22', '23'], 'ncols': 10}
    while True:
        json = collector.get_today_json()
        yield json

@app.route('/')
def index():
    return render_template('index.html')

genout = generator() # initate the function out of the scope of update route

@app.route("/update",methods=['GET'])
def update():
    global genout
    return next(genout)

def run(args):
    sc = WebClient(SLACK_BOT_TOKEN)

    if not os.path.exists(args.output):
        os.mkdir(args.output)

    assert os.path.exists(args.setup), "setup file does not exist: " + args.setup

    global collector
    collector = Collector(args.setup, args.output)
    collector.set_min_distance_to_stop(args.min_dist_to_stop)
    collector.set_min_distance_between_stops(args.min_dist_between_stops)
    collector.set_min_time_between_stops(args.min_time_diff)
    collector.set_stop_radius(args.stop_radius)
    collector.set_order(args.order)
    collector.set_late_time(args.late_min)
    collector.set_slack(sc, args.slack_channel)
    collector.start_collecting()

    app.run(debug=True)

def main(args):
    parser = argparse.ArgumentParser(description='''Help Page''')
    parser.add_argument("-o",
                        "--output",
                        required=True,
                        type=str,
                        help="Directory in which to store the outputs")
    parser.add_argument("--setup",
                        required=True,
                        type=str,
                        help="File containing a CSV with the setup to run the app: route_long_name,stop,week,sat,sun")
    parser.add_argument("--order",
                        required=False,
                        default=100,
                        type=int,
                        help="How many points on each side to use for the comparison to consider comparator(n, n+x) to be True.")
    parser.add_argument("--min_time_diff",
                        required=False,
                        default=1200,
                        type=int,
                        help="Maximum time difference in seconds. Default is 1200 (20 minutes)")
    parser.add_argument("--min_dist_between_stops",
                        required=False,
                        default=3500,
                        type=int,
                        help="Minimu distance in meters that must be passed by vehicle between two stops for the route to be counted as completed.")
    parser.add_argument("--min_dist_to_stop",
                        required=False,
                        default=250,
                        type=int,
                        help="Minimum distance in meters between the location of the bus and location of the stop for the stop to be counted as reached.")
    parser.add_argument("--stop_radius",
                        required=False,
                        default=50,
                        type=int,
                        help="Radius of each stop. The time at which the bus is reported to have departed a stop is calulated as the last time it was within the radius of it's closest position to the stop. For example, if a bus stopped 10 meters past the designated stopping position, once departure has been calulated, the departure will be calulated as the last time the bus was recorded 10+50m away from the stop position.")
    parser.add_argument("--slack_channel",
                        required=True,
                        type=str,
                        help="Name or ID of the slack chnnel to which the bot will post departures and other information")
    parser.add_argument("--late_min",
                        required=False,
                        type=int,
                        default=5,
                        help="number of minutes after whichto send late notifications to slack. Updates will then arrive every N minutes where N is the value specified by this argument.")

    parser.set_defaults(func=run)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])