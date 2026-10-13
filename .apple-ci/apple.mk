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
#   SIGNING_OLD             files that held the owner's signing settings before Signing.xcconfig,
#                           which `make project` warns about while they exist
#
# It provides: project, build, build-ios, build-mac, test-app, swift-test, tools, signing,
# build-number and update-apple-ci (which also refreshes .apple-ci/build-number.sh and the shared
# Claude instructions in .apple-ci/claude). The app's Makefile defines test, ci-linux and ci-macos (and its own targets).
# None of these becomes the default goal: `make` alone runs the app's own first rule.

# Restored at the end of this file, so the rules below don't take the default goal.
APPLE_CI_DEFAULT_GOAL := $(.DEFAULT_GOAL)

XCODEGEN ?= xcodegen
XCODEBUILD ?= xcodebuild
SWIFT ?= swift
CONFIG ?= Debug
IOS_SIMULATOR ?= iPhone 17
DERIVED_DATA ?= $(CURDIR)/.build/DerivedData
# test-app's result bundles: when the tests fail, their failures are printed from them, since -quiet
# names the failing tests and nothing else.
TEST_RESULTS ?= $(CURDIR)/.build/TestResults
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

# Signing (README.md, "Signing"): the owner's team lives in Signing.xcconfig at the repository's root,
# which git ignores and every configuration of the app includes, so pulling and regenerating the
# project keep it. `make signing TEAM=ABCDE12345` writes it; `make project` does when it's missing
# and J23N_TEAM is set in the environment. Neither runs in an agent's session (CLAUDECODE is set):
# the file is the owner's.
SIGNING_XCCONFIG ?= Signing.xcconfig
SIGNING_OLD ?=
TEAM ?= $(J23N_TEAM)

.PHONY: project build build-ios build-mac test-app test-app-ios test-app-mac test-app-none swift-test tools \
	signing build-number update-apple-ci

# The Xcode project, generated from the spec when the spec (or an input) is newer.
project: $(XCODEPROJ)/project.pbxproj

$(XCODEPROJ)/project.pbxproj: $(PROJECT_SPEC) $(PROJECT_INPUTS) | $(PROJECT_PREREQUISITES)
	@command -v $(XCODEGEN) >/dev/null 2>&1 || { echo "XcodeGen is missing: make tools (brew install xcodegen)"; exit 1; }
	@[ -f $(SIGNING_XCCONFIG) ] || [ -z "$(J23N_TEAM)" ] || [ -n "$$CLAUDECODE" ] || $(MAKE) --no-print-directory signing TEAM='$(J23N_TEAM)'
	@for old in $(SIGNING_OLD); do [ ! -f "$$old" ] || echo "warning: $$old is no longer read: move its settings to $(SIGNING_XCCONFIG)"; done
	USER="$${USER:-$$(id -un)}" $(XCODEGEN) generate --spec $(PROJECT_SPEC) --quiet
	@touch $@

build: $(addprefix build-,$(PLATFORMS))

build-ios: project $(APP_PREREQUISITES)
	$(XCODE) -destination '$(IOS_BUILD_DESTINATION)' build $(UNSIGNED)

build-mac: project $(APP_PREREQUISITES)
	$(XCODE) -destination '$(MAC_DESTINATION)' build $(UNSIGNED)

test-app: $(addprefix test-app-,$(TEST_APP_PLATFORMS))

test-app-ios: project $(APP_PREREQUISITES)
	@rm -rf '$(TEST_RESULTS)/ios.xcresult'
	$(XCODE) -destination '$(IOS_TEST_DESTINATION)' -resultBundlePath '$(TEST_RESULTS)/ios.xcresult' \
	  $(TEST_APP_FLAGS) test $(UNSIGNED) || { $(call show-test-failures,$(TEST_RESULTS)/ios.xcresult); exit 1; }

test-app-mac: project $(APP_PREREQUISITES)
	@rm -rf '$(TEST_RESULTS)/mac.xcresult'
	$(XCODE) -destination '$(MAC_DESTINATION)' -resultBundlePath '$(TEST_RESULTS)/mac.xcresult' \
	  $(TEST_APP_FLAGS) test $(SIGNED_LOCALLY) || { $(call show-test-failures,$(TEST_RESULTS)/mac.xcresult); exit 1; }

# The failures in a result bundle, with their messages and places.
show-test-failures = echo "Test failures ($(1)):"; xcrun xcresulttool get test-results summary --path '$(1)' || true

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

# Writes the owner's team into Signing.xcconfig (gitignored), keeping the file's other settings.
signing:
	@[ -z "$$CLAUDECODE" ] || { echo "make signing is the owner's: agents don't write $(SIGNING_XCCONFIG)"; exit 1; }
	@[ -n "$(TEAM)" ] || { echo "Usage: make signing TEAM=<your Apple Developer team ID> (or set J23N_TEAM)"; exit 2; }
	@[ -s $(SIGNING_XCCONFIG) ] || printf '%s\n' \
		'// Your signing settings on this Mac. Git ignores this file, and every configuration of the app' \
		'// includes it (j23n/apple-ci README.md, "Signing"). make signing TEAM=… sets the team.' > $(SIGNING_XCCONFIG)
	@grep -v '^DEVELOPMENT_TEAM[[:space:]]*=' $(SIGNING_XCCONFIG) > $(SIGNING_XCCONFIG).tmp; \
		echo 'DEVELOPMENT_TEAM = $(TEAM)' >> $(SIGNING_XCCONFIG).tmp; mv $(SIGNING_XCCONFIG).tmp $(SIGNING_XCCONFIG)
	@echo "$(SIGNING_XCCONFIG): DEVELOPMENT_TEAM = $(TEAM)"

# The build number the next build gets: the number of commits on HEAD (build-number.sh).
build-number:
	@git rev-list --count HEAD

# Replaces this copy with apple-ci's current one.
# apple.mk itself, the build number script, and the shared Claude instructions CLAUDE.md imports
# (claude/update.sh).
update-apple-ci:
	curl -fsSL $(APPLE_CI_RAW)/make/apple.mk -o .apple-ci/apple.mk
	curl -fsSL $(APPLE_CI_RAW)/make/build-number.sh -o .apple-ci/build-number.sh
	chmod +x .apple-ci/build-number.sh
	curl -fsSL $(APPLE_CI_RAW)/claude/update.sh | APPLE_CI_RAW=$(APPLE_CI_RAW) sh -s -- apps
	@git status --short -- .apple-ci .github/pull_request_template.md

# Empty when the app defined no rule before the include, so its next rule becomes the default.
.DEFAULT_GOAL := $(APPLE_CI_DEFAULT_GOAL)
