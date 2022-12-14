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

from slack import WebClient

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]


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

    def reset(self):
        self.schedule = [[[x, []] for x in self.week],
                         [[x, []] for x in self.week],
                         [[x, []] for x in self.week],
                         [[x, []] for x in self.week],
                         [[x, []] for x in self.week],
                         [[x, []] for x in self.sat],
                         [[x, []] for x in self.sun]]

    def parse_times(self, tms):
        res = []
        for x in tms:
            st = datetime.strptime(x, self.FMT)
            tst = datetime.time(st)
            res.append(tst)

        return sorted(res)

    def get_last(self):
        wd = datetime.now().weekday()
        if wd == 5:  # saturday
            return self.sat[-1]
        elif wd == 6:
            return self.sun[-1]
        else:
            return self.week[-1]

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
        closest_dist_idxs = argrelextrema(np.array(self.v_distances[vid][1]), np.less_equal, order=order_n)[
            0]  # todo: replace container list with np.array to avoid this conversions
        # select all that are also closer than min distance
        closest_dist_idxs = [c for c in closest_dist_idxs if self.v_distances[vid][1][c] < min_dist_to_stop]
        # remove duplicates close in time
        res = []
        for ci in closest_dist_idxs:
            if any(abs(self.v_distances[vid][0][ci] - timestamp_b) < min_time_between_stops for timestamp_b in
                   self.v_distances[vid][0][:ci]):
                continue
            res.append(ci)

        # make sure appropriate distance has been travelled or that the bus departed if the first in the day
        closest_dist_idxs = []
        found_stop = 0
        prev_idx = 0
        trim_to_idx = 0  # index to which the observations are to be trimmed if stops found
        for i, c in enumerate(res):
            if i == len(res) - 1:  # last one
                remaining_dists = self.v_distances[vid][1][c:]
                if len(remaining_dists) > 0 and max(
                        remaining_dists) > min_dist_to_stop:  # departed from last observation
                    closest_dist_idxs.append(c)
                    found_stop = 1
                    trim_to_idx = len(self.v_distances[vid][1])
            else:
                sub_dists = self.v_distances[vid][1][c:res[i + 1]]  # distance between current and next index
                if len(sub_dists) > 0 and max(sub_dists) >= min_dist_between_stops:
                    closest_dist_idxs.append(c)
                    prev_idx = c
                    found_stop = 1
                    trim_to_idx = res[i + 1]

        departures = []
        for c in closest_dist_idxs:
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

    # todo: idintify missed schedule

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
                if v - yesterday_midnight < 0:  # value is before yesterdays midnight
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

    def _collecting(self, lock):
        threading.Timer(1.0, self._collecting, [lock]).start()

        # check if day passed - if did - reset
        midnight = datetime.combine(date.today(), datetime.min.time())  # midnight
        cur_time = datetime.combine(midnight.date(),
                                    datetime.now().time())  # by removing date from now and adding one from midnight - we ensure they are the same
        time_delta = (cur_time - midnight).total_seconds()

        if self.log_date != date.today():  # trigger resets and cleanup of old data
            self.log_date = date.today()
            res = self.reset()  # todo: transfer data?

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


def run(args):
    sc = WebClient(SLACK_BOT_TOKEN)

    if not os.path.exists(args.output):
        os.mkdir(args.output)

    assert os.path.exists(args.setup), "setup file does not exist: " + args.setup

    collector = Collector(args.setup, args.output)
    collector.set_min_distance_to_stop(args.min_dist_to_stop)
    collector.set_min_distance_between_stops(args.min_dist_between_stops)
    collector.set_min_time_between_stops(args.min_time_diff)
    collector.set_stop_radius(args.stop_radius)
    collector.set_order(args.order)
    collector.set_late_time(args.late_min)
    collector.set_slack(sc, args.slack_channel)
    collector.start_collecting()


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
