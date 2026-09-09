# geotoolcn as a service, for languages with no binding of their own.
#
#   docker run --rm -p 8080:8080 ghcr.io/13cohen/geotoolcn
#   curl 'localhost:8080/reverse?lat=39.9042&lng=116.4074'

FROM golang:1.22-alpine AS build
WORKDIR /src

# The dataset is not committed per language, so bring it in from the Python
# package the way the sync script does.
COPY packages/go/go.mod ./packages/go/
COPY packages/go/ ./packages/go/
COPY GeoToolCN/data/china.full.gtc GeoToolCN/data/china_admin.json ./GeoToolCN/data/
RUN cp GeoToolCN/data/china.full.gtc GeoToolCN/data/china_admin.json packages/go/data/

WORKDIR /src/packages/go
# No cgo, so the result runs on scratch with nothing else installed.
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /geotoolcn ./cmd/geotoolcn

FROM scratch
COPY --from=build /geotoolcn /geotoolcn
EXPOSE 8080
USER 65534:65534
ENTRYPOINT ["/geotoolcn"]
CMD ["serve", "--addr", ":8080"]
