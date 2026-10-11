# MinIO + client mc, CONSTRUITS DEPUIS LES SOURCES officielles aux versions épinglées du compose.
#
# Pourquoi : MinIO n'est plus publié sur Docker Hub ni sur quay.io (la distribution communautaire est passée aux sources seules) :
# `docker pull minio/minio:RELEASE.…` répond « pull access denied ». Un serveur neuf, la CI ou une reconstruction ne peuvent donc plus
# démarrer la pile avec l'image officielle. Cette image reconstruit les MÊMES versions ; `go install` vérifie l'intégrité des sources
# par la base de sommes de contrôle de Go (sum.golang.org). Le serveur et le client `mc` sont dans la même image.
#
# Remplacer ces versions = décision explicite (relecture de la note de version MinIO, migration éventuelle vers un autre stockage S3).
FROM golang:1.24-bookworm AS build
ARG MINIO_TAG=RELEASE.2025-02-18T16-25-55Z
ARG MC_TAG=RELEASE.2025-02-21T16-00-46Z
ENV CGO_ENABLED=0 GOFLAGS=-trimpath
RUN go install -ldflags "-s -w" github.com/minio/minio@${MINIO_TAG} \
 && go install -ldflags "-s -w" github.com/minio/mc@${MC_TAG}

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && rm -rf /var/lib/apt/lists/*
COPY --from=build /go/bin/minio /go/bin/mc /usr/local/bin/
EXPOSE 9000 9001
VOLUME ["/data"]
# Même contrat que l'image officielle : `server /data --console-address ":9001"` fourni par le compose.
ENTRYPOINT ["/usr/local/bin/minio"]
CMD ["server", "/data", "--console-address", ":9001"]
