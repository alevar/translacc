TranslAcc
================================================================================================

.. image:: https://img.shields.io/badge/License-GPLv3-blue.svg
    :target: https://opensource.org/licenses/GPL-3.0
    :alt: GPLv3 License

.. contents::
    :local:
    :depth: 2

Introduction
^^^^^^^^^^^^

.. image:: https://raw.githubusercontent.com/alevar/translacc/master/extras/slow.cut.001.gif

ORFanage aids in finding the best matching ORF for each transcript in the
GTF file based on evidence from one or more reference annotaitons. The method is designed to
identify cases of known ORFs fitting the query transcript both with and without modifications,
introduced by additional exons, alternative start and end sites, etc. ORFanage is also designed
to quantify any changes to the reference annotation which are introduced by the splice variation.

Installation
^^^^^^^^^^^^

$ git clone https://github.com/alevar/translacc.git
$ cd translacc
$ pip install -r requirements.txt



Getting started
^^^^^^^^^^^^^^^

Usage: SLACK_BOT_TOKEN=<slack_token> /home/sparrow/soft/transloc/translacc.pytranslacc.py [-h] -o OUTPUT --setup SETUP [--order ORDER] [--min_time_diff MIN_TIME_DIFF] [--min_dist_between_stops MIN_DIST_BETWEEN_STOPS] [--min_dist_to_stop MIN_DIST_TO_STOP]
                    [--stop_radius STOP_RADIUS] --slack_channel SLACK_CHANNEL [--late_min LATE_MIN]

Help Page

optional arguments:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        Directory in which to store the outputs
  --setup SETUP         File containing a CSV with the setup to run the app: route_long_name,stop,week,sat,sun
  --order ORDER         How many points on each side to use for the comparison to consider comparator(n, n+x) to be True.
  --min_time_diff MIN_TIME_DIFF
                        Maximum time difference in seconds. Default is 1200 (20 minutes)
  --min_dist_between_stops MIN_DIST_BETWEEN_STOPS
                        Minimu distance in meters that must be passed by vehicle between two stops for the route to be counted as completed.
  --min_dist_to_stop MIN_DIST_TO_STOP
                        Minimum distance in meters between the location of the bus and location of the stop for the stop to be counted as reached.
  --stop_radius STOP_RADIUS
                        Radius of each stop. The time at which the bus is reported to have departed a stop is calulated as the last time it was within the radius of it's closest position to the stop. For
                        example, if a bus stopped 10 meters past the designated stopping position, once departure has been calulated, the departure will be calulated as the last time the bus was recorded
                        10+50m away from the stop position.
  --slack_channel SLACK_CHANNEL
                        Name or ID of the slack chnnel to which the bot will post departures and other information
  --late_min LATE_MIN   number of minutes after whichto send late notifications to slack. Updates will then arrive every N minutes where N is the value specified by this argument.