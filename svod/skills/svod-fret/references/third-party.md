# Third-party provenance

This optional package contains SVOD adapters, a launcher and a report renderer, not vendored FRET or solver binaries. The local explicit build downloads upstream FRET from https://github.com/NASA-SW-VnV/fret at cf0f913cc15c41705e803593297e89cd6056b839. FRET identifies its license as Apache License 2.0 and credits its contributors in CONTRIBUTORS.md; the complete downloaded checkout retains LICENSE.pdf and original source attribution. The adapters use the genuine compiler/analysis API without replacing the solver.

JKind/JRealizability release artifacts are fetched from https://github.com/andreaskatis/jkind-1/releases/tag/v2.2 and verified against scripts/jkind.sha256. Preserve upstream license/attribution when redistributing an image. npm dependencies and Linux packages have their own licenses; npm lock pins sources/integrities, it is not a substitute for a redistribution license audit.

The Docker base image is digest-pinned in scripts/Dockerfile. A local image build is authorized; uploading an image or release is not part of this package's implementation scope. Before any later publication, review the complete image's third-party notices, including FRET, JKind, Z3, Java, Node and npm packages. This file does not claim that a container redistribution audit has been completed.
