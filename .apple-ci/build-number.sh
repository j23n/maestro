#!/bin/sh
# The build number: sets CFBundleVersion in the Info.plist of the product Xcode just built to the
# number of commits on HEAD (`git rev-list --count HEAD`), so a build of a later commit always has
# a higher one, in Xcode and from the command line alike (README.md, "Build numbers").
#
# Each app keeps a copy in .apple-ci/ (make update-apple-ci), and every target that ships a bundle
# (the app and its extensions, which must have the app's build number) runs it last, from
# project.yml:
#
#   postBuildScripts:
#     - name: Build number
#       script: '"$SRCROOT/.apple-ci/build-number.sh"'
#       inputFiles: ["$(TARGET_BUILD_DIR)/$(INFOPLIST_PATH)"]
#       basedOnDependencyAnalysis: false
#
# The input file makes it run after Xcode writes the Info.plist. The target needs
# ENABLE_USER_SCRIPT_SANDBOXING = NO, since the script reads .git.
set -eu

plist="$TARGET_BUILD_DIR/$INFOPLIST_PATH"
if ! count=$(git -C "$SRCROOT" rev-list --count HEAD 2>/dev/null); then
  echo "warning: no git history in $SRCROOT, so the build number stays as the project sets it"
  exit 0
fi
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $count" "$plist"
echo "Build number: $count"
