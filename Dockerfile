# geotoolcn as a service, for languages with no binding of their own.
#
#   docker run --rm -p 8080:8080 ghcr.io/13cohen/geotoolcn
#   curl 'localhost:8080/reverse?lat=39.9042&lng=116.4074'

FROM golang:1.22-alpine AS build
WORKDIR /src

# packages/go carries its own dataset — go:embed cannot reach outside the
# module — so the Go module alone is enough to build from.
COPY packages/go/ ./packages/go/

WORKDIR /src/packages/go
# No cgo, so the result runs on scratch with nothing else installed.
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /geotoolcn ./cmd/geotoolcn

FROM scratch
COPY --from=build /geotoolcn /geotoolcn
EXPOSE 8080
USER 65534:65534
ENTRYPOINT ["/geotoolcn"]
CMD ["serve", "--addr", ":8080"]
