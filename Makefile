# Italiano — every command a contributor or agent runs (docs/10 § Makefile targets).
# GNU Make 3.81 compatible (macOS): no .ONESHELL, no !=, no $(file ...).
# A target that belongs to a later task prints "not yet (task Mx.y)" and exits 0.

SHELL := /bin/bash
UV ?= uv
SWIFT ?= swift
XCODEBUILD ?= xcodebuild
PYPROJECT := --project pipeline
CONTENT := $(UV) run $(PYPROJECT) content
UNAME := $(shell uname)

XCODEPROJ := App/Italiano.xcodeproj
SCHEME := Italiano
IOS_SIM ?= iPhone 17
IPAD_SIM ?= iPad Air 11-inch (M3)
CONFIG ?= Debug
UNSIGNED := CODE_SIGNING_ALLOWED=NO
ADHOC := CODE_SIGN_IDENTITY=- CODE_SIGN_STYLE=Manual DEVELOPMENT_TEAM= CODE_SIGN_ENTITLEMENTS=App/Config/Italiano-NoCloud.entitlements

PACK_FILE := App/Italiano/Resources/Content/content.sqlite

.PHONY: ensure-pack help bootstrap data test test-core test-storage test-pipeline annotate check-content pack mini-pack \
	pack-release build-ios build-mac test-app test-ui screenshots lint-guards archive ci

help:
	@echo "make bootstrap | data | test | test-core | test-storage | test-pipeline | annotate | check-content"
	@echo "make pack | mini-pack | pack-release | lint-guards | ci"
	@echo "make build-ios | build-mac | test-app | test-ui | screenshots   (macOS with Xcode 27)"
	@echo "make archive CONFIG=Study   (owner only)"

# ---------------------------------------------------------------- setup

bootstrap:
	$(UV) sync $(PYPROJECT)
	-git lfs pull
	$(MAKE) data
	-$(MAKE) ensure-pack
	$(SWIFT) package resolve --package-path Packages/LearningCore
	$(SWIFT) package resolve --package-path Packages/Storage
	@echo "Tool versions:"
	@$(SWIFT) --version 2>&1 | head -1
	@$(UV) --version
	@$(UV) run $(PYPROJECT) python --version
	@if command -v xcodebuild >/dev/null 2>&1; then xcodebuild -version | head -1; fi

data:
	$(UV) run $(PYPROJECT) python -m itcontent.data_fetch

# ---------------------------------------------------------------- tests

# Storage (GRDB 7.11.1) builds and tests on Linux too, so it runs everywhere; macOS stays the reference.
test: test-core test-storage test-pipeline check-content

test-core:
	$(SWIFT) test --package-path Packages/LearningCore

test-storage:
	$(SWIFT) test --package-path Packages/Storage

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

pack-release:
	$(CONTENT) build --release --allow-partial

# The bundled dev pack is a build output (gitignored, docs/04 § Pack build): build it when it's missing, without
# running the content checks, so a content error never blocks building the app.
ensure-pack:
	@if [ -f $(XCODEPROJ)/project.pbxproj ] && [ ! -f $(PACK_FILE) ]; then \
	  echo "building the dev pack ($(PACK_FILE))"; $(CONTENT) build; fi

# ---------------------------------------------------------------- app (macOS, Xcode 27)

build-ios: ensure-pack
	@if [ ! -f $(XCODEPROJ)/project.pbxproj ]; then echo "not yet (task M0.2: the owner creates $(XCODEPROJ))"; else \
	$(XCODEBUILD) -project $(XCODEPROJ) -scheme $(SCHEME) -configuration $(CONFIG) \
	  -destination 'generic/platform=iOS Simulator' build $(UNSIGNED); fi

build-mac: ensure-pack
	@if [ ! -f $(XCODEPROJ)/project.pbxproj ]; then echo "not yet (task M0.2: the owner creates $(XCODEPROJ))"; else \
	$(XCODEBUILD) -project $(XCODEPROJ) -scheme $(SCHEME) -configuration $(CONFIG) \
	  -destination 'platform=macOS' build $(UNSIGNED); fi

test-app: ensure-pack
	@if [ ! -f $(XCODEPROJ)/project.pbxproj ]; then echo "not yet (task M0.2: the owner creates $(XCODEPROJ))"; else \
	$(XCODEBUILD) -project $(XCODEPROJ) -scheme $(SCHEME) -skip-testing:ItalianoUITests \
	  -destination 'platform=iOS Simulator,name=$(IOS_SIM)' test $(UNSIGNED) && \
	$(XCODEBUILD) -project $(XCODEPROJ) -scheme $(SCHEME) -skip-testing:ItalianoUITests \
	  -destination 'platform=macOS' test $(ADHOC); fi

test-ui: ensure-pack
	@if [ ! -f $(XCODEPROJ)/project.pbxproj ]; then echo "not yet (task M0.2: the owner creates $(XCODEPROJ))"; else \
	$(XCODEBUILD) -project $(XCODEPROJ) -scheme $(SCHEME) -only-testing:ItalianoUITests \
	  -destination 'platform=iOS Simulator,name=$(IOS_SIM)' test $(UNSIGNED) && \
	$(XCODEBUILD) -project $(XCODEPROJ) -scheme $(SCHEME) -only-testing:ItalianoUITests \
	  -destination 'platform=macOS' test $(ADHOC); fi

screenshots: ensure-pack
	@if [ ! -f $(XCODEPROJ)/project.pbxproj ]; then echo "not yet (task M0.2: the owner creates $(XCODEPROJ))"; else \
	mkdir -p artifacts/screens && \
	$(XCODEBUILD) -project $(XCODEPROJ) -scheme $(SCHEME) -only-testing:ItalianoUITests/Screenshots \
	  -destination 'platform=iOS Simulator,name=$(IOS_SIM)' -resultBundlePath artifacts/screens/ios.xcresult test $(UNSIGNED) && \
	$(XCODEBUILD) -project $(XCODEPROJ) -scheme $(SCHEME) -only-testing:ItalianoUITests/MacScreens \
	  -destination 'platform=macOS' -resultBundlePath artifacts/screens/mac.xcresult test $(ADHOC); fi

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
	@if [ ! -f $(XCODEPROJ)/project.pbxproj ]; then echo "not yet (task M0.2)"; exit 1; fi
	$(CONTENT) build --release --allow-partial
	bash scripts/archive.sh "$(CONFIG)"

ci: lint-guards test-core test-storage test-pipeline data check-content
	@if [ "$(UNAME)" = "Darwin" ]; then $(MAKE) build-ios build-mac test-app; fi
