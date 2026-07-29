# The build environment for Python 0.9.1 through 2.5.
#
# Pinned, because "what my laptop had installed" is not provenance. Two
# things here decide what the interpreter oracle is allowed to claim, and
# both are deliberate:
#
# 1. **The i386 toolchain.** These releases were written when `int`,
#    `long` and a pointer were all 32 bits, and the oldest of them pass
#    `va_list *` around in `modsupport.c`, which is not valid on the
#    x86-64 ABI. Built 64-bit, Python 1.0 and 1.1 segfault inside
#    `chr()`, so `import string` fails and every module reports as
#    absent. That is a false absence, which is the one error this dataset
#    cannot tolerate, so the pre-1.5 releases are built for the
#    architecture they were written for.
#
# 2. **The 64-bit development libraries.** From 1.5 on, `setup.py` and
#    `Modules/Setup` build an extension only if its library is present,
#    so this list is what "importable in a default build on a modern
#    Unix" means. A library missing here reports as a module missing from
#    the release, so the set is pinned rather than inherited from the
#    host.
#
# `libgdbm-compat-dev` is here for a reason worth remembering: it carries
# `ndbm.h`, and installing `libgdbm-dev` without it is worse than
# installing neither. `configure` then believes dbm is available while the
# header it needs is missing, and 2.2 fails to build outright rather than
# quietly skipping the module.
#
# Deliberately absent: no attempt is made to satisfy `_ssl` or `_tkinter`
# for the 2.x line. OpenSSL 3 is far past what that era's `_ssl` compiles
# against, so those modules fail to build here and the oracle stays quiet
# about them rather than reporting them absent. The archives answer for
# `ssl` and `Tkinter`.
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN dpkg --add-architecture i386 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        gcc-multilib \
        libc6-dev-i386 \
        libcrypt-dev:i386 \
        zlib1g-dev \
        libbz2-dev \
        libexpat1-dev \
        libgdbm-dev \
        libgdbm-compat-dev \
        libncurses-dev \
        libreadline-dev \
        libsqlite3-dev \
        libtirpc-dev \
    && rm -rf /var/lib/apt/lists/*
