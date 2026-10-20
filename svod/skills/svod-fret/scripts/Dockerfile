FROM node:20.19.5-bookworm-slim@sha256:9e70124bd00f47dd023e349cd587132ae61892acc0e47ed641416c3e18f401c3
RUN apt-get update && apt-get install -y --no-install-recommends openjdk-17-jre-headless=17.0.20.1+1-1~deb12u1 z3=4.8.12-3.1 curl ca-certificates python3 make g++ && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /opt/jkind && for f in jkind jkind.jar jrealizability jlustre2kind; do curl -fL --retry 3 https://github.com/andreaskatis/jkind-1/releases/download/v2.2/$f -o /opt/jkind/$f; done && chmod +x /opt/jkind/jkind /opt/jkind/jrealizability /opt/jkind/jlustre2kind
ENV PATH="/opt/jkind:${PATH}" NODE_ENV=production
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/* && git config --global url."https://github.com/".insteadOf ssh://git@github.com/
WORKDIR /opt/probe
COPY jkind.sha256 ./
RUN sha256sum -c jkind.sha256
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY runtime/source ./source
COPY runtime/LICENSE.pdf runtime/CONTRIBUTORS.md /opt/probe/upstream-attribution/
COPY api.js webpack.config.cjs ./
RUN cd /opt/probe/source && ../node_modules/.bin/webpack --config /opt/probe/webpack.config.cjs
COPY run.cjs ./run.cjs
COPY jrealizability-log /opt/probe/bin/jrealizability
RUN chmod +x /opt/probe/bin/jrealizability && mkdir -p /root/Documents
ENV PATH="/opt/probe/bin:${PATH}"
CMD ["node","/opt/probe/dist/cli.cjs","--help"]
