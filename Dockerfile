# geotoolcn as a service, for languages with no binding of their own.
#
#   docker run --rm -p 8080:8080 ghcr.io/13cohen/geotoolcn
#   curl 'localhost:8080/reverse?lat=39.9042&lng=116.4074'

# Cross-compiled rather than emulated: the build stage always runs on the
# builder's own architecture and Go targets $TARGETARCH, so the arm64 image
# does not depend on QEMU being registered on the CI runner.
FROM --platform=$BUILDPLATFORM golang:1.26-alpine AS build
ARG TARGETOS
ARG TARGETARCH
# Injected by release.yml from the cli-v* tag. Without it the binary reports
# "dev", which is the honest answer for a local `docker build`.
ARG VERSION=dev
WORKDIR /src

# packages/go carries its own dataset — go:embed cannot reach outside the
# module — so the Go module alone is enough to build from.
COPY packages/go/ ./packages/go/

WORKDIR /src/packages/go
# No cgo, so the result runs on scratch with nothing else installed.
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH \
    go build -trimpath -ldflags="-s -w -X main.version=$VERSION" \
    -o /geotoolcn ./cmd/geotoolcn

FROM scratch
COPY --from=build /geotoolcn /geotoolcn
EXPOSE 8080
USER 65534:65534
ENTRYPOINT ["/geotoolcn"]
CMD ["serve", "--addr", ":8080"]
