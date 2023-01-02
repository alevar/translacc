#!/usr/bin/env python

import os
import sys
import json
import math
import argparse
import requests
import threading
import numpy as np
import pandas as pd
from itertools import product
from scipy.signal import argrelextrema
from datetime import datetime, date, timezone, timedelta

# courtesy of https://www.omnicalculator.com/other/latitude-longitude-distance
def deg2rad(deg):
	rad = deg* math.pi / 180.0
	return rad

def sphDist(lat1,long1,lat2,long2):
	r = 6371 * 1000
	dist = 2 * r * np.arcsin(
						math.sqrt(
							math.pow(
								np.sin((lat2-lat1)/2.0),
								2
							) + 
							np.cos(lat1)*np.cos(lat2)*math.pow(np.sin((long2-long1)/2.0),
																2)
						)
					)
	return dist

def distance(l1,l2):
	res = sphDist(deg2rad(l1[0]),deg2rad(l1[1]),deg2rad(l2[0]),deg2rad(l2[1]))
	return res

class Schedule:
	def __init__(self,week,sat,sun):
		self.FMT = '%I:%M%p'

		self.week = self.parse_times(week)
		self.sat = self.parse_times(sat)
		self.sun =  self.parse_times(sun)

	def parse_times(self,tms):
		res = []
		for x in tms:
			st = datetime.strptime(x,self.FMT)
			tst = datetime.time(st)
			res.append(tst)

		return sorted(res)

	def get_last(self):
		wd = datetime.now().weekday()
		if wd == 5: # saturday
			return self.sat[-1]
		elif wd == 6:
			return self.sun[-1]
		else:
			return self.week[-1]

class Vehicle:
	def __init__(self,vid,route_id):
		self.vid = vid
		self.route_id = route_id
		self.travel = []
		self.made_stop = False

	def update(self,timestamp,position):
		if len(self.travel) == 0 or timestamp>self.travel[-1][0]:
			self.travel.append((timestamp,position))
			return True
		return False

	def reset(self):
		self.travel = list()
		self.has_departed = False

	def get_id(self):
		return self.vid

	def set_departed(self):
		self.made_stop = True
	def has_departed(self):
		return self.made_stop

class Stop:
	def __init__(self,id,code,name,position):
		self.id = id
		self.code = code
		self.name = name
		self.position = position
		self.schedule = None
		self.observed_departures = list()
		self.v_distances = dict()

		self.last_stop = 0 # indicates the index of the last stop from the schedule which occurred

	def update(self,vid,timestamp,vpos):
		self.v_distances.setdefault(vid,[[],[]])
		self.v_distances[vid][0].append(timestamp)
		self.v_distances[vid][1].append(distance(vpos,self.position))

		return self.v_distances[vid][1][-1]

	def time_diff(self,t1,t2,min_diff=0): # returns true if two values differ by more min_diff number of seconds
		return

	def depart(self,
			   vehicle, # vehicle ID
			   order_n, #
			   min_dist_to_stop,
			   min_dist_between_stops,
			   min_time_between_stops): # returns 0 if no new departure detected - returns 1 if there is departure
		assert vehicle.get_id() in self.v_distances,"requested vehicle is not available"

		# find local minima etc
		# get index of the closest point
		closest_dist_idxs = argrelextrema(np.array(self.v_distances[vehicle.get_id()][1]),np.less_equal,order=order_n)[0] # todo: replace container list with np.array to avoid this ocnversion
		# select all that are also closer than min distance
		closest_dist_idxs = [c for c in closest_dist_idxs if self.v_distances[vehicle.get_id()][1][c]<min_dist_to_stop]
		# remove duplicates close in time
		res = []
		for ci in closest_dist_idxs:
			if any(abs(self.v_distances[vehicle.get_id()][0][ci] - timestamp_b) < min_time_between_stops for timestamp_b in self.v_distances[vehicle.get_id()][0][:ci]):
				continue
			res.append(ci)

			# lastly make sure the bus travelled an appropriate distance before departure or is the first stop for the bus
		found_stop = 0
		prev_idx = 0
		for i,c in enumerate(res):
			# we need to handle cases of the first departure of the day - there may not have been max distance reached yet
			sub_dists = self.v_distances[vehicle.get_id()][1][prev_idx:c]
			max_dist = max(sub_dists)
			if (max_dist>=min_dist_between_stops) or \
				(i==0 and not vehicle.has_departed()): # vehicle has not yet departed
				self.observed_departures.append(self.v_distances[vehicle.get_id()][0][c])
				print(self.name+" : "+str(self.observed_departures[-1]))
				prev_idx = c
				found_stop = 1

		# lastly, clean up distances up until this departure to prepare for the next round
		if found_stop:
			self.v_distances[vehicle.get_id()][1] = self.v_distances[vehicle.get_id()][1][:prev_idx]

		# if departure is found - record it and remove the vehicle record up to this point
		return found_stop

	def get_delta(self,t1,t2):
		ct1 = datetime.combine(date.today(),t1)
		ct2 = datetime.combine(date.today(),t2)
		td = (ct1-ct2).total_seconds()
		return td

	def _closest(self,l1,l2,res,max_delta,recycle=False,future_only=False):
		if len(l1)==0 or len(l2)==0:
			return res
		p = None
		if not future_only:
			p = product(l1, l2)
		else:
			p = [x for x in list(product(l1,l2)) if x[0]<=x[1]]
			if len(p)==0:
				return res

		cl = min(p, key=lambda t: abs(self.get_delta(t[0],t[1])))
		if abs(self.get_delta(cl[0],cl[1]))>max_delta:
			for x in l1:
				res.append((x,0))
			return res

		else:
			res.append(cl)
			t1 = [x for x in l1]
			t1.remove(cl[0])
			t2 = [x for x in l2]
			if not recycle:
				t2.remove(cl[1])
			self._closest(t1,t2,res,max_delta,recycle,future_only)

	def reset(self):
		self.observed_departures = list()
		self.v_distances = dict()

	def set_schedule(self,week,sat,sun):
		self.schedule = Schedule(week,sat,sun)

	def get_position(self):
		return self.position

	def get_code(self):
		return self.code

	def get_name(self):
		return self.name

class Collector:
	def __init__(self,setup_fname,outdir):
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

		# initialize output files
		self.outdir = outdir.rstrip("/")+"/"
		if not os.path.exists(self.outdir):
			os.mkdir(self.outdir)

		self.log_all_fname = None
		self.log_all_fp = None

		# LOGIC
		self.setup()
		self.init_logs()

	def set_min_distance_to_stop(self,min_distance_to_stop):
		self.min_dist_to_stop = min_distance_to_stop

	def set_min_distance_between_stops(self,min_dist_between_stops):
		self.min_dist_between_stops = min_dist_between_stops

	def set_min_time_between_stops(self,min_time_between_stops):
		self.min_time_between_stops = min_time_between_stops

	def set_order(self,order):
		self.order_n = order

	def init_logs(self):
		if self.log_all_fp is not None:
			self.log_all_fp.close()
		cur_date = datetime.now().strftime("%Y%m%d")
		self.log_all_fname = self.outdir+"log.all."+cur_date+".csv"
		if os.path.exists(self.log_all_fname):
			print("new log file already exists - overwriting: "+self.log_all_fname)

		self.log_all_fp = open(self.log_all_fname,"w+")

	def reset(self):
		for sid,s in self.stops.items():
			s.reset()
		for vid,v in self.vehicles.items():
			v.reset()

		self.init_logs()

	def _collecting(self,lock):
		threading.Timer(1.0, self._collecting,[lock]).start()

		# check if day passed - if did - reset
		midnight = datetime.combine(date.today(),datetime.min.time()) # midnight
		cur_time = datetime.combine(midnight.date(),datetime.now().time()) # by removing date from now and adding one from midnight - we ensure they are the same
		time_delta = (cur_time-midnight).total_seconds()
		if 86400-time_delta <= 1*60: # if within 1 minute of midnight - has to refresh
			self.reset()

		url = "https://feeds.transloc.com/3/vehicle_statuses?agencies=641&include_arrivals=true"
		payload={}
		headers = {}
		response = requests.request("GET", url, headers=headers, data=payload)

		output = response.json()

		if output["success"] is not True:
			exit(1)

		# for each stop we can now check which buses crossed it and estimate time at which the stop occurred
		for v in output["vehicles"]:
			# check that the vehicle belongs to the correct route
			if not v["route_id"]==self.route_id:
				continue

			# update vehicle positioning if changed
			timestamp = v["timestamp"]
			self.vehicles.setdefault(v["id"],Vehicle(v["id"],v["route_id"]))
			updated = self.vehicles[v["id"]].update(timestamp,v["position"])

			if updated:
				for sid,stop in self.stops.items():
					timestamp = v["timestamp"]
					stop_dist = stop.update(v["id"],timestamp,v["position"])
					stop_departed = stop.depart(self.vehicles[v["id"]],self.order_n,self.min_dist_to_stop,self.min_dist_between_stops,self.min_time_between_stops) # check if departed - if did mark and edit accordingly - resets the vehicle history for the stop and for the vehicle
					if stop_departed:
						v.set_departed()

					with lock:
						out_line = str(sid)+","+str(v["id"])+","+str(timestamp)+","+str(stop_dist)+","+str(stop_departed)+"\n"
						self.log_all_fp.write(out_line)


	def start_collecting(self):
		lock = threading.Lock()
		self._collecting(lock)

	def setup(self):
		assert os.path.exists(self.setup_fname),"setup file does not exist: "+self.setup_fname
		with open(self.setup_fname,"r") as inFP:
			for line in inFP:
				if line[0]=="#": # header line
					continue

				lcs = line.strip().split(",")
				assert len(lcs)==5,"incorrect number of columns in the setup file. Expected the following format: route_long_name,stop,week,sat,sun"

				# ROUTE
				if self.route_long_name is None:
					self.route_long_name = lcs[0]
					self.init_route()
				else:
					assert self.route_long_name == lcs[0],"multiple routes are not supported at this time. Please ensure your setup file has a single route name specified in the first column"

				# STOP
				sid = self.init_stop(lcs[1])
				self.stops[sid].set_schedule(lcs[2].split(";"),lcs[3].split(";"),lcs[4].split(";"))

	def init_stop(self,stop_name):

		# now get stops using the route ID
		url = "https://feeds.transloc.com/3/stops?agencies=641&include_routes=true"
		payload={}
		headers = {}
		response = requests.request("GET", url, headers=headers, data=payload)

		output = response.json()

		rcv_routes = {r["id"]:r for r in output["routes"]}
		rcv_stops = {s["id"]:s for s in output["stops"]}

		found_stop = False
		stop_sid = None
		for rid,r in rcv_routes.items():
			if r["id"]==self.route_id:
				for s in r["stops"]:
					if rcv_stops[s]["name"] != stop_name:
						continue
					else:
						self.stops[s] = None
						found_stop = True
						stop_sid = s

		assert found_stop,"didn't find requested stop: "+stop_name

		# lastly add additional information about the stops
		for sid,s in rcv_stops.items():
			if s["id"] in self.stops:
				self.stops[s["id"]] = Stop(s["id"],s["code"],s["name"],s["position"])

		return stop_sid

	def init_route(self):
		url = "https://feeds.transloc.com/3/routes?agencies=641&include_arrivals=true"
		payload={}
		headers = {}
		response = requests.request("GET", url, headers=headers, data=payload)

		output = response.json()
		assert output["success"] is True,"unsuccessful attempt at getting routes"
		assert "routes" in output,"incorrect response: "+output

		found_route = False
		for r in output["routes"]:
			if r["long_name"]==self.route_long_name:
				found_route = True
				self.route_id = r["id"]

		assert found_route,"requested route was not found"

def run(args):
	if not os.path.exists(args.output):
		os.mkdir(args.output)

	assert os.path.exists(args.setup),"setup file does not exist: "+args.setup

	collector = Collector(args.setup,args.output)
	collector.set_min_distance_to_stop(args.min_dist_to_stop)
	collector.set_min_distance_between_stops(args.min_dist_between_stops)
	collector.set_min_time_between_stops(args.min_time_diff)
	collector.set_order(args.order)
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


	parser.set_defaults(func=run)
	args = parser.parse_args()
	args.func(args)

if __name__=="__main__":
	main(sys.argv[1:])