#!/usr/bin/python3

"""
(c) 2014 Florian Will <florian.will@gmail.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""


import datetime
import subprocess
import re
import sys
import time

glStatusCommit = subprocess.check_output(["git", "rev-parse", "master"]).decode('utf-8').strip()
download = "https://github.com/w-flo/mesa-GL-status/archive/%s.zip" % (glStatusCommit)

msg = subprocess.check_output(["git", "pull"], cwd="mesa").decode('utf-8').strip()
if msg != "": print(msg, file=sys.stderr)
latestCommit = subprocess.check_output(["git", "rev-parse", "--short", "master"], cwd="mesa").decode('utf-8').strip()
historyCommits = subprocess.check_output(["git", "log", "--format=%H", "docs/GL3.txt"], cwd="mesa").decode('utf-8').strip().split("\n")

glVersionRegex = re.compile('GL (\d+\.\d+)(, GLSL \d+\.\d+)?( --- all DONE: ([a-z0-9]+(, )?)*)?')
allDoneRegex = re.compile(' --- all DONE: (([a-z0-9]+(, )?)*)')

glFeatureRegex = re.compile('  (\S.*?)  \s*(\S.*)')
featureStatusDoneRegex = re.compile('DONE \((([a-z0-9/\+]*(, )?)*)\)')
featureStatusWipRegex = re.compile('(started|in progress) \(([a-zA-Z ]+)\)')
featureStatusDependsOnGLSLRegex = re.compile('DONE \(all drivers that support GLSL( \d+.\d+)?\)')
featureStatusDependsOnFeatureRegex = re.compile('DONE \(all drivers that support (.*)\)')

glToGLSLVersion = {}


class Driver:
	def __init__(self, name):
		if name == "": raise Exception("Empty driver name")
		self.name = name
		self.supportedFeatures = set()
		self.restrictions = {}
		self.supportedGLSL = ""
		self.featureSince = {}

	def supports(self, feature, restriction=None):
		self.supportedFeatures.add(feature)
		if restriction is not None:
			self.restrictions[feature] = restriction

	def isSupported(self, feature):
		return (feature in self.supportedFeatures)

	def getRestriction(self, feature):
		return self.restrictions[feature] if feature in self.restrictions else None

	def supportsGLSL(self, version):
		self.supportedGLSL = version

	def featureSupportedSince(self, feature, commit):
		self.featureSince[feature] = commit

	def getFeatureSince(self, feature):
		return self.featureSince[feature] if feature in self.featureSince else None

	def __str__(self):
		return "Driver %s with %s features." % (self.name, len(self.supportedFeatures))

	def __hash__(self):
		return self.name.__hash__()

	def __eq__(self, other):
		return self.name.__eq__(other)

class Feature:
	def __init__(self, name):
		if name == "": raise Exception("Empty feature name")
		self.name = name
		self.done = False
		self.assignedTo = ""
		self.glslVersion = ""
		self.dependsOn = ""
		self.unknownComment = ""

	def setDone(self):
		self.done = True

	def isDone(self):
		return self.done

	def setAssignedTo(self, assignedTo):
		self.assignedTo = assignedTo

	def dependsOnGLSL(self, version):
		self.glslVersion = version

	def dependsOnFeature(self, feature):
		self.dependsOn = feature

	def setUnknownComment(self, comment):
		self.unknownComment = comment

	def __str__(self):
		return "Feature %s (done: %s)" % (self.name, self.done)

	def __hash__(self):
		return self.name.__hash__()

	def __eq__(self, other):
		return self.name.__eq__(other.name)

def updateKnownDrivers(knownDrivers, driverNames):
	knownDrivers.update({driver: Driver(driver) for driver in (driverNames-knownDrivers.keys())})


def parseCommit(commit):
	knownDrivers = {} # key is driver name
	knownFeatures = {} # key is GL version

	currentGLVersion = ""
	headerFeature = None
	allDoneDrivers = set()

	msg = subprocess.check_output(["git", "checkout", commit, "--", "docs/GL3.txt"], cwd="mesa").decode('utf-8').strip()
	if msg != "": print(msg, file=sys.stderr)

	file = open("mesa/docs/GL3.txt", "r")
	for line in file:

		versionResult = glVersionRegex.match(line)
		if versionResult is not None:
			allDoneDrivers = set()
			currentGLVersion = versionResult.group(1)
			if versionResult.lastindex >= 2 and versionResult.group(2) is not None:
				glslVersion = versionResult.group(2).strip()[7:]
				glToGLSLVersion[currentGLVersion] = glslVersion
			else:
				glslVersion = glToGLSLVersion[currentGLVersion]
			knownFeatures[currentGLVersion] = []

			if versionResult.lastindex >= 3 and versionResult.group(3) is not None:
				allDoneResult = allDoneRegex.match(versionResult.group(3))
				if allDoneResult is not None:
					allDoneDrivers = set(allDoneResult.group(1).split(", "))
					updateKnownDrivers(knownDrivers, allDoneDrivers)
					for driver in allDoneDrivers: knownDrivers[driver].supportsGLSL(glslVersion)

		elif line.strip() != "" and line[0] != " ":
			currentGLVersion = ""

		glFeatureResult = glFeatureRegex.match(line)
		if glFeatureResult is not None:
			if currentGLVersion == "": continue

			feature = Feature(glFeatureResult.group(1))
			knownFeatures[currentGLVersion].append(feature)

			for driver in allDoneDrivers:
				knownDrivers[driver].supports(feature)

			if feature.name[0:2] != "- ": headerFeature = feature
			else:
				for driver in knownDrivers.values():
					if driver.isSupported(headerFeature): driver.supports(feature)
					continue

			status = glFeatureResult.group(2).strip()
			if status == "not started" or status == "started (currently stalled)" or status == "DONE":
				# DONE means mesa supports this, but no drivers (in addition to the "all done" list of this GL version)
				continue

			if status == "DONE (all drivers)":
				feature.setDone()
				continue

			featureStatusDoneResult = featureStatusDoneRegex.match(status)
			if featureStatusDoneResult is not None:
				doneDrivers = [x.split("/") for x in featureStatusDoneResult.group(1).split(", ")]
				if [""] not in doneDrivers:
					updateKnownDrivers(knownDrivers, set([x[0] for x in doneDrivers]))
					for doneDriver in doneDrivers:
						knownDrivers[doneDriver[0]].supports(feature)
						if len(doneDriver) > 1: knownDrivers[doneDriver[0]].supports(feature, doneDriver[1])
				continue

			featureStatusWipResult = featureStatusWipRegex.match(status)
			if featureStatusWipResult is not None:
				assignedTo = featureStatusWipResult.group(2)
				feature.setAssignedTo(assignedTo)
				continue

			featureStatusDependsOnGLSLResult = featureStatusDependsOnGLSLRegex.match(status)
			if featureStatusDependsOnGLSLResult is not None:
				feature.dependsOnGLSL(featureStatusDependsOnGLSLResult.group(1))
				continue

			featureStatusDependsOnFeatureResult = featureStatusDependsOnFeatureRegex.match(status)
			if featureStatusDependsOnFeatureResult is not None:
				otherFeature = featureStatusDependsOnFeatureResult.group(1)
				feature.dependsOnFeature(otherFeature)
				continue

			feature.setUnknownComment(status)

	changes = True
	while changes:
		changes = False
		for featureList in knownFeatures.values():
			for feature in featureList:
				for driver in knownDrivers.values():
					if driver.isSupported(feature): continue

					if feature.isDone():
						driver.supports(feature)
						changes = True
					if feature.glslVersion != "" and feature.glslVersion is not None and \
							driver.supportedGLSL != "" and \
							(float(feature.glslVersion) <= float(driver.supportedGLSL)):
						driver.supports(feature)
						changes = True
					if feature.glslVersion is None and driver.supportedGLSL != "":
						driver.supports(feature)
						changes = True
					if feature.dependsOn != "":
						for driverFeature in driver.supportedFeatures:
							if feature.dependsOn in driverFeature.name:
								driver.supports(feature)
								changes = True
								break

	return (knownFeatures, knownDrivers)


oldestCommit = ""
(features, drivers) = parseCommit(latestCommit)
i = 1
for historyCommit in historyCommits:
	print("%s/%s: %s" % (i, len(historyCommits), historyCommit), file=sys.stderr)
	i += 1
	(oldFeatures, oldDrivers) = parseCommit(historyCommit)

	for featureList in oldFeatures.values():
		for feature in featureList:
			for driver in oldDrivers.values():
				if driver.name in drivers and drivers[driver.name].isSupported(feature) \
						and driver.isSupported(feature) \
						and drivers[driver.name].getRestriction(feature) == driver.getRestriction(feature):
					drivers[driver.name].featureSupportedSince(feature, historyCommit)
					oldestCommit = historyCommit

driverOrdering = sorted(drivers)

markup = ""
markup += '<html><head><title>Mesa GL3 Status</title><link rel="stylesheet" type="text/css" href="style.css"><body><h1>Mesa GL3 Status and History</h1><p>Green: implemented, red: not implemented, yellow: work in progress, grey: failed to parse correctly. Some of the greens, all of the greys, and any reds containing some text show more info in a tooltip when hovering the cell.</p><p>Inspired by <a href="http://creak.foolstep.com/mesamatrix/">The OpenGL vs Mesa matrix</a> by Romain "Creak" Failliot, but this script uses <a href="%s">very ugly python code (download link)</a> instead of PHP. It adds some history info to the matrix to make up for the ugly code.' % download
markup += '<p>Generated %s, based on the <a href="http://cgit.freedesktop.org/mesa/mesa/tree/docs/GL3.txt?h=%s">latest Mesa git master commit at that time, %s</a>.</p></body></html>' % (time.strftime("%Y-%m-%d %H:%M:%S"), latestCommit, latestCommit)
for glVersion in sorted(features):
	markup += "<h2>OpenGL Version %s (GLSL %s)</h2><table><tr><th>Feature</th>" % (glVersion, glToGLSLVersion[glVersion])
	for driver in driverOrdering:
		markup += "<th>%s</th>" % driver
	markup += "</tr>"
	for feature in features[glVersion]:
		markup += '<tr><td class=\"feature\">%s</td>' % feature.name
		for driverName in driverOrdering:
			driver = drivers[driverName]
			text = ""
			title = ""
			if feature.unknownComment != "":
				cssClass = "unknown"
				text = "???"
				title = "Status: %s" % feature.unknownComment
			elif feature.assignedTo != "":
				cssClass = "assigned"
				text = feature.assignedTo
				title = "Work in progress, assigned to %s" % feature.assignedTo
			elif driver.isSupported(feature):
				cssClass = "yep"
				if driver.getRestriction(feature) is not None:
					text = driver.getRestriction(feature)
					title = "This feature is restricted to %s hardware. " % driver.getRestriction(feature)
				commit = driver.getFeatureSince(feature)
				if commit is not None and commit != oldestCommit:
					gitInfo = subprocess.check_output(["git", "show", "-s", "--format=%ct|%cn|%an|%h|%s", commit], cwd="mesa").decode('utf-8').strip().split("|")
					date = datetime.datetime.fromtimestamp(int(gitInfo[0])).strftime('%Y-%m-%d %H:%M:%S')
					days = round((time.time() - int(gitInfo[0])) / (60*60*24))
					if days < 30: text = "%sd" % days
					if title != "": title += "\n"
					title += "Feature since %s (%s)\nAuthor of GL3.txt change: %s\nCommitter of GL3.txt change: %s\nSubject: %s" % (date, gitInfo[3], gitInfo[2], gitInfo[1], gitInfo[4])
			else:
				cssClass = "nope"
				if feature.glslVersion is None:
					text = "GLSL"
					title = "Feature requires GLSL, but the script assumed that this driver does not support GLSL."
				elif feature.glslVersion != "":
					text = "GLSL %s" % (feature.glslVersion)
					title = "Feature requires GLSL %s, but the script assumed that this driver does not support GLSL %s." % (feature.glslVersion, feature.glslVersion)
				elif feature.dependsOn != "":
					text = "Depend"
					title = "Feature requires %s, but that is not done yet for this driver." % feature.dependsOn
			markup += '<td class=\"%s\"' % cssClass
			if title != "": markup += ' title="%s"' % title
			markup += '>%s</td>' % text
		markup += "</tr>"
	markup += "</table>"

print(markup)