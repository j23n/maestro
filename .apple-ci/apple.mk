# apple.mk: the build contract's shared rules (j23n/apple-ci, make/apple.mk; README.md there).
# Each app keeps a copy in .apple-ci/apple.mk and includes it from its Makefile. Don't edit the
# copy: change apple-ci, then run `make update-apple-ci` in the app.
# GNU Make 3.81, macOS's own: no .ONESHELL, no !=, no $(file ...).
#
# The app's Makefile sets, before the include:
#   PROJECT_SPEC            the XcodeGen spec, such as project.yml or App/project.yml
#   XCODEPROJ               the project XcodeGen writes from it (gitignored)
#   SCHEME                  the app's scheme
#   PLATFORMS               where the app runs: ios, mac, or "ios mac"
# and when it needs them:
#   SWIFT_PACKAGES          package folders whose tests `make swift-test` runs, in order
#   PROJECT_INPUTS          more files that should regenerate the project (xcconfigs)
#   PROJECT_PREREQUISITES   targets to make before generating it (a built resource)
#   APP_PREREQUISITES       targets to make before every app build and test (the same, when
#                           the project can outlive the resource)
#   TEST_APP_PLATFORMS      where `make test-app` runs the app's tests: ios, mac, both, or none
#   TEST_APP_FLAGS          more xcodebuild flags for them (-skip-testing:…, -only-testing:…)
#   IOS_SIMULATOR           the simulator `make test-app` uses (default iPhone 17)
#
# It provides: project, build, build-ios, build-mac, test-app, swift-test, tools and
# update-apple-ci. The app's Makefile defines test, ci-linux and ci-macos (and its own targets).
# None of these becomes the default goal: `make` alone runs the app's own first rule.

# Restored at the end of this file, so the rules below don't take the default goal.
APPLE_CI_DEFAULT_GOAL := $(.DEFAULT_GOAL)

XCODEGEN ?= xcodegen
XCODEBUILD ?= xcodebuild
SWIFT ?= swift
CONFIG ?= Debug
IOS_SIMULATOR ?= iPhone 17
DERIVED_DATA ?= $(CURDIR)/.build/DerivedData
XCODEBUILD_FLAGS ?= -quiet
SWIFT_PACKAGES ?=
PROJECT_INPUTS ?=
PROJECT_PREREQUISITES ?=
APP_PREREQUISITES ?=
TEST_APP_PLATFORMS ?= $(firstword $(PLATFORMS))
TEST_APP_FLAGS ?=

IOS_BUILD_DESTINATION ?= generic/platform=iOS Simulator
IOS_TEST_DESTINATION ?= platform=iOS Simulator,name=$(IOS_SIMULATOR),OS=latest
MAC_DESTINATION ?= platform=macOS

# Builds are unsigned, as in CI; the Mac's tests are signed to run locally, without a team.
UNSIGNED ?= CODE_SIGNING_ALLOWED=NO
SIGNED_LOCALLY ?= CODE_SIGN_IDENTITY=- CODE_SIGN_STYLE=Manual DEVELOPMENT_TEAM= PROVISIONING_PROFILE_SPECIFIER=

XCODE = $(XCODEBUILD) $(XCODEBUILD_FLAGS) -project $(XCODEPROJ) -scheme $(SCHEME) -configuration $(CONFIG) \
	-derivedDataPath '$(DERIVED_DATA)'

APPLE_CI_RAW ?= https://raw.githubusercontent.com/j23n/apple-ci/main

.PHONY: project build build-ios build-mac test-app test-app-ios test-app-mac test-app-none swift-test tools \
	update-apple-ci

# The Xcode project, generated from the spec when the spec (or an input) is newer.
project: $(XCODEPROJ)/project.pbxproj

$(XCODEPROJ)/project.pbxproj: $(PROJECT_SPEC) $(PROJECT_INPUTS) | $(PROJECT_PREREQUISITES)
	@command -v $(XCODEGEN) >/dev/null 2>&1 || { echo "XcodeGen is missing: make tools (brew install xcodegen)"; exit 1; }
	USER="$${USER:-$$(id -un)}" $(XCODEGEN) generate --spec $(PROJECT_SPEC) --quiet
	@touch $@

build: $(addprefix build-,$(PLATFORMS))

build-ios: project $(APP_PREREQUISITES)
	$(XCODE) -destination '$(IOS_BUILD_DESTINATION)' build $(UNSIGNED)

build-mac: project $(APP_PREREQUISITES)
	$(XCODE) -destination '$(MAC_DESTINATION)' build $(UNSIGNED)

test-app: $(addprefix test-app-,$(TEST_APP_PLATFORMS))

test-app-ios: project $(APP_PREREQUISITES)
	$(XCODE) -destination '$(IOS_TEST_DESTINATION)' $(TEST_APP_FLAGS) test $(UNSIGNED)

test-app-mac: project $(APP_PREREQUISITES)
	$(XCODE) -destination '$(MAC_DESTINATION)' $(TEST_APP_FLAGS) test $(SIGNED_LOCALLY)

test-app-none:
	@echo "This app has no app tests."

# The packages' tests, which run on Linux too.
swift-test:
	@for package in $(SWIFT_PACKAGES); do \
	  echo "$(SWIFT) test --package-path $$package"; \
	  $(SWIFT) test --package-path $$package || exit 1; \
	done

# What a Mac needs to build the app, besides Xcode.
tools:
	@command -v $(XCODEGEN) >/dev/null 2>&1 || brew install xcodegen

# Replaces this copy with apple-ci's current one.
update-apple-ci:
	curl -fsSL $(APPLE_CI_RAW)/make/apple.mk -o .apple-ci/apple.mk
	@git diff --stat -- .apple-ci/apple.mk

# Empty when the app defined no rule before the include, so its next rule becomes the default.
.DEFAULT_GOAL := $(APPLE_CI_DEFAULT_GOAL)
