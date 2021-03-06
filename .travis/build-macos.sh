#!/bin/bash
set -e

UNAME=darwin
EX=
#set EX to sudo if required.

exitcode=0
plugins=""
plugins_suffix=""
if [[ -n "$PLUGINS" ]]; then
  plugins="--plugins=${PLUGINS}"
  plugins_suffix="-${PLUGINS}"
fi

case "$BUILD_ARCH" in
  32bit)
    pypy .build/build.py $plugins
    exitcode=$?
    cp rsqueak rsqueak-x86-${UNAME}$plugins_suffix-jit-$TRAVIS_COMMIT || true
    # pypy .build/jittests.py
    # $EX rm -rf .build/pypy/rpython/_cache
    ;;
  64bit)
    pypy .build/build.py -- $plugins
    exitcode=$?
    cp rsqueak rsqueak-x86_64-${UNAME}$plugins_suffix-jit-$TRAVIS_COMMIT || true
    # pypy .build/jittests.py
    # $EX rm -rf .build/pypy/rpython/_cache
    ;;
  lldebug)
    pypy .build/build.py --lldebug -Ojit
    exitcode=$?
    cp rsqueak rsqueak-x86-${UNAME}-dbg-$TRAVIS_COMMIT || true
    # $EX rm -rf .build/pypy/rpython/_cache
    ;;
  *) exit 0 ;;
esac

exit $exitcode
