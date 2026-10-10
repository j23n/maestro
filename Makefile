# Italiano — every command a contributor or agent runs (docs/10 § Makefile targets).
# GNU Make 3.81 compatible (macOS): no .ONESHELL, no !=, no $(file ...).
# A target that belongs to a later task prints "not yet (task Mx.y)" and exits 0.
# The project, app build and app test targets follow the build contract the j23n apps share (j23n/apple-ci):
# .apple-ci/apple.mk is a copy of its rules (`make update-apple-ci` refreshes it), included below.

SHELL := /bin/bash
UV ?= uv
SWIFT ?= swift
XCODEBUILD ?= xcodebuild
XCODEGEN ?= xcodegen
PYPROJECT := --project pipeline
CONTENT := $(UV) run $(PYPROJECT) content
UNAME := $(shell uname)

PROJECT_SPEC := project.yml
XCODEPROJ := Italiano.xcodeproj
# Where the owner's signing settings were before Signing.xcconfig at the root: make project warns while it exists.
SIGNING_OLD := App/Config/Signing.xcconfig
SCHEME := Italiano
PLATFORMS := ios mac
IOS_SIMULATOR ?= iPhone 17
IPAD_SIM ?= iPad Air 11-inch (M3)
CONFIG ?= Debug
# Regenerate the project when project.yml or an xcconfig file is newer (ADR-19).
PROJECT_INPUTS := $(wildcard App/Config/*.xcconfig)
PACK_FILE := App/Italiano/Resources/Content/content.sqlite
# The bundled dev pack is built before the project is generated, and before every app build and test.
PROJECT_PREREQUISITES := ensure-pack
APP_PREREQUISITES := ensure-pack
# Unit and snapshot tests on the iOS Simulator (unsigned) and the Mac (ad hoc, without iCloud); the UI tests are
# make test-ui's.
TEST_APP_PLATFORMS := ios mac
TEST_APP_FLAGS := -skip-testing:ItalianoUITests
# Without iCloud, so the owner's Signing.xcconfig can't turn sync on in a test run without the entitlement (docs/02).
SIGNED_LOCALLY := CODE_SIGN_IDENTITY=- CODE_SIGN_STYLE=Manual DEVELOPMENT_TEAM= CODE_SIGN_ENTITLEMENTS=App/Config/Italiano-NoCloud.entitlements \
	ITA_ICLOUD_ENTITLEMENT=NO ITA_SYNC_ENABLED=NO
ADHOC := $(SIGNED_LOCALLY)

include .apple-ci/apple.mk

.PHONY: ensure-pack help bootstrap data test test-app-logic test-core test-storage test-pipeline lint-pipeline annotate \
	check-content pack mini-pack pack-release pack-determinism test-ui screenshots lint-guards archive ci ci-linux ci-macos

help:
	@echo "make bootstrap | data | test | test-core | test-storage | test-pipeline | annotate | check-content"
	@echo "make pack | mini-pack | pack-release | lint-guards | ci"
	@echo "make project | build | build-ios | build-mac | test-app | test-ui | screenshots   (macOS with Xcode 27 and XcodeGen)"
	@echo "make ci-linux | ci-macos   what CI runs (j23n/apple-ci's shared workflows)"
	@echo "make archive CONFIG=Study   (owner only)"

# ---------------------------------------------------------------- setup

bootstrap:
	$(UV) sync $(PYPROJECT)
	-git lfs pull
	$(MAKE) data
	-$(MAKE) ensure-pack
	$(SWIFT) package resolve --package-path Packages/LearningCore
	$(SWIFT) package resolve --package-path Packages/Storage
	@if [ "$(UNAME)" = "Darwin" ]; then $(MAKE) project || echo "skipped the Xcode project: install XcodeGen, then make project"; fi
	@echo "Tool versions:"
	@$(SWIFT) --version 2>&1 | head -1
	@$(UV) --version
	@$(UV) run $(PYPROJECT) python --version
	@if command -v xcodebuild >/dev/null 2>&1; then xcodebuild -version | head -1; fi

data:
	$(UV) run $(PYPROJECT) python -m itcontent.data_fetch

# ---------------------------------------------------------------- tests

# Storage (GRDB 7.11.1) builds and tests on Linux too, so it runs everywhere; macOS stays the reference.
test: test-core test-storage test-pipeline check-content test-app-logic

test-core:
	$(SWIFT) test --package-path Packages/LearningCore

test-storage:
	$(SWIFT) test --package-path Packages/Storage

# The App's platform-neutral view models, adapters' fakes and their tests, compiled against the packages (any OS).
test-app-logic:
	bash scripts/check-app-logic.sh --test

test-pipeline:
	$(UV) run $(PYPROJECT) pytest pipeline -q

# ---------------------------------------------------------------- content

annotate:
	$(CONTENT) annotate

check-content:
	$(CONTENT) lint
	$(CONTENT) annotate --check
	$(CONTENT) check

pack: check-content
	$(CONTENT) build

mini-pack:
	$(CONTENT) build --mini
	$(UV) run $(PYPROJECT) python -m itcontent.pack.assessment_fixture

pack-release:
	$(CONTENT) build --release --allow-partial

# The bundled dev pack is a build output (gitignored, docs/04 § Pack build): build it when it's missing, without
# running the content checks, so a content error never blocks building the app.
ensure-pack:
	@if [ ! -f $(PACK_FILE) ]; then echo "building the dev pack ($(PACK_FILE))"; $(CONTENT) build; fi

# ---------------------------------------------------------------- app (macOS, Xcode 27)

# The Xcode project is generated from project.yml at the root by XcodeGen (ADR-19 as amended) and gitignored. apple.mk's
# `make project` writes Italiano.xcodeproj, building the dev pack first when it's missing, and `build-ios`,
# `build-mac` (`make build` for both) and `test-app` regenerate it whenever project.yml or an xcconfig file is newer.
# Sources are synchronized folders, so adding a Swift file needs no regeneration.

# The UI tests and screenshots build in the same DerivedData and on the same simulator runtime as test-app
# (apple.mk's $(XCODE) and destinations).
test-ui: ensure-pack project
	$(XCODE) -only-testing:ItalianoUITests -destination '$(IOS_TEST_DESTINATION)' test $(UNSIGNED) && \
	$(XCODE) -only-testing:ItalianoUITests -destination '$(MAC_DESTINATION)' test $(ADHOC)

screenshots: ensure-pack project
	mkdir -p artifacts/screens && \
	$(XCODE) -only-testing:ItalianoUITests/Screenshots -destination '$(IOS_TEST_DESTINATION)' \
	  -resultBundlePath artifacts/screens/ios.xcresult test $(UNSIGNED) && \
	$(XCODE) -only-testing:ItalianoUITests/MacScreens -destination '$(MAC_DESTINATION)' \
	  -resultBundlePath artifacts/screens/mac.xcresult test $(ADHOC)

# ---------------------------------------------------------------- guards and CI

lint-guards:
	bash scripts/check-core-imports.sh
	python3 scripts/check-contrast.py
	python3 scripts/gen-tokens.py --check
	bash scripts/check-app-logic.sh

# [owner] Signs with the owner's team: never run by agents (ADR-19). Builds the release pack, swaps it into the
# bundle for the archive only and restores the dev pack on exit.
archive:
	@if [ -n "$$CLAUDECODE" ]; then echo "make archive is the owner's step (ADR-19)."; exit 1; fi
	$(MAKE) project
	$(CONTENT) build --release --allow-partial
	bash scripts/archive.sh "$(CONFIG)"

# What CI runs (j23n/apple-ci's shared workflows, .github/workflows/ci.yml): Linux, then the Mac.
ci-linux: lint-guards data test lint-pipeline

ci-macos: test-storage pack-determinism build test-app

ci: ci-linux
	@if [ "$(UNAME)" = "Darwin" ]; then $(MAKE) build test-app; fi

lint-pipeline:
	$(UV) run $(PYPROJECT) ruff check pipeline
	$(UV) run $(PYPROJECT) ruff format --check pipeline

# The dev pack built twice must be the same bytes (docs/04 § Pack build).
pack-determinism: data
	$(CONTENT) build
	@a="$$($(CONTENT) pack-hash)"; $(CONTENT) build; \
	  test "$$a" = "$$($(CONTENT) pack-hash)" || { echo "pack build is not deterministic"; exit 1; }
