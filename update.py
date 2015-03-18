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
import html
import subprocess
import re
import sys
import time

glStatusCommit = subprocess.check_output(["git", "rev-parse", "master"]).decode('utf-8').strip()
download = "https://github.com/w-flo/mesa-GL-status/archive/%s.zip" % (glStatusCommit)

generationTime = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
msg = subprocess.check_output(["git", "fetch"], cwd="mesa").decode('utf-8').strip()
if msg != "": print(msg, file=sys.stderr)
msg = subprocess.check_output(["git", "reset", "--hard", "origin/master"], cwd="mesa").decode('utf-8').strip()
if msg != "": print(msg, file=sys.stderr)


latestCommit = subprocess.check_output(["git", "rev-parse", "--short", "master"], cwd="mesa").decode('utf-8').strip()
historyCommits = subprocess.check_output(["git", "log", "--format=%H", "docs/GL3.txt"], cwd="mesa").decode('utf-8').strip().split("\n")

glVersionRegex = re.compile('GL (\d+\.\d+)(, GLSL \d+\.\d+)?( --- all DONE: ([a-z0-9 \(\*\)]+(, )?)*)?')
allDoneRegex = re.compile(' --- all DONE: (([a-z0-9 \(\*\)]+(, )?)*)')

glFeatureRegex = re.compile('  (\S.*?)  \s*(\S.*)')
featureStatusDoneRegex = re.compile('DONE \((([a-z0-9/\+]*( \(\*\))?(, )?)*)\)')
featureStatusWipRegex = re.compile('(started|in progress) \((.+)\)')
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
		self.firstTimeFound = set()

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

	def isSupportedSince(self, oldDriver, feature):
		return self.isSupported(feature) \
				and oldDriver.isSupported(feature) \
				and self.getRestriction(feature) == oldDriver.getRestriction(feature)

	def featureSupportedSince(self, feature, commit):
		self.featureSince[feature] = commit

	def getFeatureSince(self, feature):
		return self.featureSince[feature] if feature in self.featureSince else None

	def setFirstTimeFound(self, feature):
		self.firstTimeFound.add(feature)

	def wasFirstTimeFound(self, feature):
		return feature in self.firstTimeFound

	def getChanges(self, olderDriver):
		changes = ""
		newFeatures = self.supportedFeatures - olderDriver.supportedFeatures
		if len(newFeatures) != 0:
			changes += "%s now supports %s. " % (self.name, ', '.join([featureToLink(x) for x in newFeatures]))
		goneFeatures = olderDriver.supportedFeatures - self.supportedFeatures
		if len(goneFeatures) != 0:
			changes += "%s no longer supports %s. " % (self.name, ', '.join([featureToLink(x) for x in goneFeatures]))
		if changes == "": return None
		else: return changes

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
					allDoneDrivers = set([drivername.strip(" (*)") for drivername in allDoneResult.group(1).split(", ")])
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
			if status == "not started" or status == "started (currently stalled)":
				continue

			if status == "DONE (all drivers)" or status == "DONE":
				feature.setDone()
				continue

			featureStatusDoneResult = featureStatusDoneRegex.match(status)
			if featureStatusDoneResult is not None:
				doneDrivers = [x.split("/") for x in featureStatusDoneResult.group(1).split(", ")]
				if [""] not in doneDrivers:
					doneDrivers = [[x[0].replace(" (*)", "")] for x in doneDrivers]
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
recentChanges = []
newerDrivers = {}
newerFeatures = {}
newerCommit = ""
(features, drivers) = parseCommit(latestCommit)


def featureToLink(feature):
	global features
	if True in [(feature in featureList) for featureList in features.values()]:
		return '<a href="#%s">%s</a>' % (feature.__hash__(), feature.name.strip(" -"))
	else:
		return feature.name.strip(" -")

i = 1
for historyCommit in historyCommits:
	#print("%s/%s: %s" % (i, len(historyCommits), historyCommit), file=sys.stderr)
	i += 1
	(oldFeatures, oldDrivers) = parseCommit(historyCommit)

	for featureList in oldFeatures.values():
		for feature in featureList:
			for oldDriver in oldDrivers.values():
				if oldDriver.name not in drivers: continue
				newDriver = drivers[oldDriver.name]
				if newDriver.isSupportedSince(oldDriver, feature) and not newDriver.wasFirstTimeFound(feature):
					newDriver.featureSupportedSince(feature, historyCommit)
					oldestCommit = historyCommit
				else:
					newDriver.setFirstTimeFound(feature)

				if oldDriver.name in newerDrivers:
					recentChange = newerDrivers[oldDriver.name].getChanges(oldDriver)
					if recentChange is not None:
						recentChanges.append((newerCommit, recentChange))
				newerDrivers[oldDriver.name] = oldDriver

			if feature.name in newerFeatures:
				newerFeature = newerFeatures[feature.name]
				if newerFeature.unknownComment != feature.unknownComment:
					if newerFeature.unknownComment == "":
						message = "%s: Removed comment." % featureToLink(newerFeature)
					else:
						message = "%s: New comment &quot;%s&quot;." % (featureToLink(newerFeature), newerFeature.unknownComment)
					if feature.unknownComment != "":
						message += " Old comment was &quot;%s&quot;." % feature.unknownComment
					else:
						message += " There was no comment for this feature before this commit."
					recentChanges.append((newerCommit, message))
				if newerFeature.assignedTo != feature.assignedTo:
					if newerFeature.assignedTo != "":
						recentChanges.append((newerCommit, "%s: Work in progress now assigned to %s." % (featureToLink(newerFeature), newerFeature.assignedTo)))
					else:
						recentChanges.append((newerCommit, "%s: No longer a work in progress." % featureToLink(newerFeature)))

			newerFeatures[feature.name] = feature

	newerCommit = historyCommit

driverOrdering = sorted(drivers)

markup = ""
markup += '<!DOCTYPE html><html><head><meta charset="utf-8"/><title>Mesa GL3 Status</title><link rel="stylesheet" type="text/css" href="style.css"><body><h1>Mesa GL3 Status and History</h1><p>Green: implemented, red: not implemented, yellow: work in progress, grey: failed to parse correctly. Some of the greens and any reds containing some text show more info in a tooltip when hovering the cell. All times are in UTC.</p><p>Inspired by <a href="http://creak.foolstep.com/mesamatrix/">The OpenGL vs Mesa matrix</a> by Romain "Creak" Failliot, but this script uses <a href="%s">very ugly python code (download link)</a> instead of PHP. It adds some history info to the matrix to make up for the ugly code.' % download
markup += '<p>Generated %s UTC<br />Based on the <a href="http://cgit.freedesktop.org/mesa/mesa/tree/docs/GL3.txt?h=%s">latest Mesa git master commit at that time, %s</a>.</p>' % (generationTime, latestCommit, latestCommit)
markup += '<h2>Changes</h2><div id="changes"><ul>'
for (commit, change) in recentChanges:
	gitInfo = subprocess.check_output(["git", "show", "-s", "--format=%ct|%s|%an", commit], cwd="mesa").decode('utf-8').strip().split("|")
	date = datetime.datetime.utcfromtimestamp(int(gitInfo[0])).strftime('%Y-%m-%d')
	markup += '<li><a href="http://cgit.freedesktop.org/mesa/mesa/commit/docs/GL3.txt?h=%s">%s</a>: %s <nobr>Author: <span class="author">%s</span></nobr>, commit message: <i>%s</i>.</li>' % (commit, date, change, gitInfo[2], gitInfo[1])
markup += '</div></ul>'
for glVersion in sorted(features):
	markup += "<h2>OpenGL Version %s (GLSL %s)</h2><table><tr><th>Feature</th>" % (html.escape(glVersion), html.escape(glToGLSLVersion[glVersion]))
	for driver in driverOrdering:
		markup += "<th>%s</th>" % html.escape(driver)
	markup += "</tr>"
	for feature in features[glVersion]:
		markup += '<tr><td class="feature"><a name="%s" />%s</td>' % (feature.__hash__(), html.escape(feature.name))
		if feature.assignedTo != "":
			markup += '<td class="assigned" title="Work in progress, assigned to %s" colspan="%s">WIP: %s</td>' % (feature.assignedTo, len(driverOrdering), feature.assignedTo)
		elif feature.unknownComment != "":
			markup += '<td class="unknown" title="The script failed to parse this status message correctly, so it is shown as plain text." colspan="%s">Status: %s</td>' % (len(driverOrdering), feature.unknownComment)
		else:
			for driverName in driverOrdering:
				driver = drivers[driverName]
				text = ""
				title = ""
				if feature.unknownComment != "":
					cssClass = "unknown"
					text = "???"
					title = "Status: %s" % feature.unknownComment
				elif driver.isSupported(feature):
					cssClass = "yep"
					if driver.getRestriction(feature) is not None:
						text = driver.getRestriction(feature)
						title = "This feature is restricted to %s hardware. " % driver.getRestriction(feature)
					commit = driver.getFeatureSince(feature)
					if commit is not None and commit != oldestCommit:
						gitInfo = subprocess.check_output(["git", "show", "-s", "--format=%ct|%cn|%an|%h|%s", commit], cwd="mesa").decode('utf-8').strip().split("|")
						date = datetime.datetime.utcfromtimestamp(int(gitInfo[0])).strftime('%Y-%m-%d %H:%M:%S')
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
				markup += '<td class=\"%s\"' % html.escape(cssClass)
				if title != "": markup += ' title="%s"' % html.escape(title).replace("\n", "&#10;")
				markup += '>%s</td>' % html.escape(text)
		markup += "</tr>"
	markup += "</table>"
markup += "</body></html>"

print(markup)
