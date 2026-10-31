# Maestro: every command a contributor, an agent and CI run. The targets follow the build contract
# the j23n apps share (j23n/apple-ci); .apple-ci/apple.mk is a copy of its rules
# (`make update-apple-ci` refreshes it). On Linux, put /opt/swift/usr/bin on the PATH first.

SHELL := /bin/bash
PYTHON ?= python3

PROJECT_SPEC := project.yml
XCODEPROJ := Maestro.xcodeproj
SCHEME := Maestro
PLATFORMS := ios mac
# Every local package under Packages/, so a new one is tested without a change here.
SWIFT_PACKAGES := $(patsubst %/Package.swift,%,$(wildcard Packages/*/Package.swift))

include .apple-ci/apple.mk

.PHONY: help bootstrap test test-tools ci-linux ci-macos clean

help:
	@echo "make bootstrap    XcodeGen and the Xcode project"
	@echo "make signing TEAM=…   your team, in Signing.xcconfig (git ignores it)"
	@echo "make test         the packages' tests and the content pipeline's (macOS and Linux)"
	@echo "make build        the app for the iOS Simulator and the Mac, unsigned"
	@echo "make test-app     the app's tests in the iOS Simulator"
	@echo "make ci-linux | ci-macos   what CI runs"

bootstrap: tools project

test: swift-test test-tools

# The content pipeline's tests (tools/). Pytest exits 5 when it finds no tests, which isn't a failure.
test-tools:
	@[ ! -d tools ] || { echo "$(PYTHON) -m pytest tools"; $(PYTHON) -m pytest tools || [ $$? -eq 5 ]; }

ci-linux: test

# Linux runs the pipeline's tests on every push, so the Mac runs the packages' tests (their
# Apple-only code included), then builds and tests the app.
ci-macos: swift-test build test-app

clean:
	rm -rf $(XCODEPROJ) .build Packages/*/.build
