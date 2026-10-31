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

# The app bundles the content database and the starter packs, built by `make content` (tools/).
# Archives for TestFlight build the real dictionary from the kaikki.org dump; other builds use a
# dump already in .build/content-sources, or a small sample so they never wait for the download.
# CONTENT=full|auto|sample overrides.
ifneq ($(filter archive archive-% testflight testflight-%,$(MAKECMDGOALS)),)
CONTENT ?= full
endif
CONTENT ?= auto
APP_PREREQUISITES := content
# The screenshot walk-through is slow and only for `make screenshots`; the reader's UI tests run.
TEST_APP_FLAGS := -skip-testing:MaestroUITests/ScreenshotTests

include .apple-ci/apple.mk

.PHONY: help bootstrap test test-tools content coverage check-texts brief draft screenshots ci-linux ci-macos clean

help:
	@echo "make bootstrap    XcodeGen and the Xcode project"
	@echo "make signing TEAM=…   your team, in Signing.xcconfig (git ignores it)"
	@echo "make test         the packages' tests and the content pipeline's (macOS and Linux)"
	@echo "make build        the app for the iOS Simulator and the Mac, unsigned"
	@echo "make test-app     the app's tests in the iOS Simulator"
	@echo "make content      the dictionary database and starter packs the app bundles (CONTENT=full for the real dictionary)"
	@echo "make coverage     what the texts cover per level, into .build/coverage.md"
	@echo "make check-texts [TEXTS=…]   check texts against their level plan and brief"
	@echo "make brief LEVEL=A2 COLLECTION=… [TITLE=…] [WINDOW=…]   a new brief aimed at the level's gaps"
	@echo "make draft TEXT=…  draft a brief's text with Claude, then check it"
	@echo "make screenshots  the main screens on an iPhone and an iPad simulator, into .build/Screenshots"
	@echo "make ci-linux | ci-macos   what CI runs"

bootstrap: tools project

test: swift-test test-tools

# The content pipeline's tests (tools/). Pytest exits 5 when it finds no tests, which isn't a failure.
test-tools:
	@[ ! -d tools ] || { echo "$(PYTHON) -m pytest tools"; $(PYTHON) -m pytest tools || [ $$? -eq 5 ]; }

# The dictionary database and the starter packs, into App/Resources/Content (git ignores them).
content:
	$(PYTHON) tools/build_content.py --mode $(CONTENT)

# Texts: level plans in content/curriculum, the checker, the coverage report and briefs
# (tools/maestro_content/curriculum.py). They read the content database, so build it with
# CONTENT=full first for real numbers; the sample dictionary links few words.
CONTENT_TOOL := PYTHONPATH=tools $(PYTHON) -m maestro_content

coverage: content
	$(CONTENT_TOOL) coverage

check-texts: content
	$(CONTENT_TOOL) check $(TEXTS)

brief: content
	@[ -n "$(LEVEL)" ] && [ -n "$(COLLECTION)" ] || { echo "usage: make brief LEVEL=A2 COLLECTION=vita-quotidiana [TITLE=…] [WINDOW=12-01..01-06]"; exit 2; }
	$(CONTENT_TOOL) brief --level $(LEVEL) --collection $(COLLECTION) $(if $(TITLE),--title "$(TITLE)") $(if $(WINDOW),--window $(WINDOW))

# The main screens on an iPhone and an iPad simulator, as PNGs in .build/Screenshots, for checking
# the UI against the mocks. The iPad runs in landscape, and the simulator saves its screenshots
# unrotated, so they're turned upright. The iPad is the first iPad Pro 13-inch the runner has, else any iPad.
SCREENSHOTS := $(CURDIR)/.build/Screenshots
IPAD_SIMULATOR ?= $(shell xcrun simctl list devices available 2>/dev/null | sed -nE 's/^ +(iPad.*) \([0-9A-F-]{36}\) .*/\1/p' | awk '/iPad Pro 13/ {print; found=1; exit} NR==1 {first=$$0} END {if (!found && first) print first}')

screenshots: project $(APP_PREREQUISITES)
	@rm -rf '$(SCREENSHOTS)' '$(TEST_RESULTS)'/screenshots-*.xcresult
	@mkdir -p '$(SCREENSHOTS)'
	@status=0; \
	for dest in 'iphone|$(IOS_SIMULATOR)' 'ipad|$(IPAD_SIMULATOR)'; do \
	  key=$${dest%%|*}; sim=$${dest#*|}; \
	  [ -n "$$sim" ] || { echo "No $$key simulator"; status=1; continue; }; \
	  echo "Screenshots on $$sim"; \
	  $(XCODE) -destination "platform=iOS Simulator,name=$$sim,OS=latest" \
	    -resultBundlePath '$(TEST_RESULTS)'/screenshots-$$key.xcresult -only-testing:MaestroUITests/ScreenshotTests \
	    test $(UNSIGNED) || status=1; \
	  $(PYTHON) tools/export_screenshots.py '$(TEST_RESULTS)'/screenshots-$$key.xcresult '$(SCREENSHOTS)' || status=1; \
	done; \
	for f in '$(SCREENSHOTS)'/iPad-*.png; do [ ! -f "$$f" ] || sips -r 270 "$$f" >/dev/null; done; \
	ls '$(SCREENSHOTS)'; exit $$status

ci-linux: test

# Linux runs the pipeline's tests on every push, so the Mac runs the packages' tests (their
# Apple-only code included), then builds and tests the app.
ci-macos: swift-test build test-app

clean:
	rm -rf $(XCODEPROJ) .build Packages/*/.build App/Resources/Content/content.sqlite App/Resources/Content/packs
