#!/usr/bin/env python

import sys
import json
import math
import argparse
import requests
import threading
import pandas as pd
import numpy as np
from datetime import datetime


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


def get_stops_for_route(route_long_name):
	url = "https://feeds.transloc.com/3/routes?agencies=641&include_arrivals=true"
	payload={}
	headers = {}
	response = requests.request("GET", url, headers=headers, data=payload)

	output = response.json()
	assert output["success"] is True,"unsuccessful attempt at getting routes"
	assert "routes" in output,"incorrect response: "+output

	found_route = False
	route_id = 0
	for r in output["routes"]:
		if r["long_name"]==route_long_name:
			found_route = True
			route_id = r["id"]

	# now get stops using the route ID
	url = "https://feeds.transloc.com/3/stops?agencies=641&include_routes=true"
	payload={}
	headers = {}
	response = requests.request("GET", url, headers=headers, data=payload)

	output = response.json()
	
	stops = {}
	for r in output["routes"]:
		if r["id"]==route_id:
			for s in r["stops"]:
				stops[s] = {}

	assert len(stops)>0,"didn't find stops for the route"

	# lastly add additional information about the stops
	for s in output["stops"]:
		if s["id"] in stops:
			stops[s["id"]]["code"] = s["code"]
			stops[s["id"]]["name"] = s["name"]
			stops[s["id"]]["position"] = s["position"]

	return route_id,stops

def collect(route_id,stops,prev_distances,lock):
	threading.Timer(1.0, collect,[route_id,stops,prev_distances,lock]).start()
	
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
		if not v["route_id"]==route_id:
			continue

		for sid,sv in stops.items():
			if sid not in [4177254,4265754]: # Broadway and Interfaith
				continue
			timestamp = v["timestamp"]
			meters = distance(v["position"],sv["position"])

			# get delta from the previous timestamp
			# if delta distance is negative - it's getting closer  if switches to positive - passed

			if v["id"] not in prev_distances[sid]:
				prev_distances[sid][v["id"]] = timestamp
			else:
				if timestamp>prev_distances[sid][v["id"]]: # update
					prev_distances[sid][v["id"]] = timestamp
					with lock:
						# if v["call_name"]=="ACAD6" and sv["code"] == "101":
						print("\t".join([str(x) for x in [sid,v["id"],timestamp,meters]]))
				else:
					continue

def run(args):
	route_id,stops = get_stops_for_route("Homewood Peabody JHMI")
	# print(stops)
	# print(distance([39.29801, -76.59408],[39.331997, -76.61723]))
	# exit()
	# print(stops)
	prev_distances = dict()
	for sid,sv in stops.items():
		prev_distances[sid] = dict()

	print("starting collection", file=sys.stderr)
	lock = threading.Lock()
	collect(route_id,stops,prev_distances,lock)

def main(args):
	
	parser = argparse.ArgumentParser(description='''Help Page''')

	parser.set_defaults(func=run)
	args = parser.parse_args()
	args.func(args)

if __name__=="__main__":
	main(sys.argv[1:])