// Package data holds the embedded dataset.
//
// The .gtc is copied in from the Python package by scripts/sync-data.sh rather
// than committed here: 6 MB per language binding adds up, and the copy needs no
// geopandas, so a fresh clone can still run the Go tests.
package data
