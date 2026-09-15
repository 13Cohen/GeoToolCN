// Package data holds the embedded dataset.
//
// Unlike the Node package's copy, this one is committed: `go get` fetches
// only what git holds, and go:embed cannot reach outside the module
// directory, so the Go module is the one binding whose dataset has to live
// in the repository. scripts/sync-data.sh refreshes it from the Python
// package after a rebuild; CI compares the two copies and fails on drift.
//
// NOTICE records where the boundaries come from and that the MIT license
// does not cover them.
package data
