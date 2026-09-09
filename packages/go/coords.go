package geotoolcn

// Conversions between WGS-84, GCJ-02 (国测局 / 高德 / 腾讯) and BD-09 (百度).
// Pure maths, no data. SPEC.md §2.11.
//
// NOTE the argument order: the six conversions take (lng, lat) — longitude
// first — while Distance takes latitude first, matching the GeoTool methods.
// The inconsistency is inherited from the Python package and preserved so the
// implementations agree. Passing a conversion (lat, lng) does not error: the
// swapped longitude falls outside the China bounding box, so the input comes
// straight back and the mistake is silent.

import "math"

const (
	gcjA  = 6378245.0
	gcjEE = 0.00669342162296594
	xPi   = math.Pi * 3000.0 / 180.0

	lngMin = 72.004
	lngMax = 137.8347
	latMin = 0.8293
	latMax = 55.8271

	earthRadiusKm = 6371.0
)

func outOfChina(lng, lat float64) bool {
	return !(lng > lngMin && lng < lngMax && lat > latMin && lat < latMax)
}

func transformLat(x, y float64) float64 {
	ret := -100.0 + 2.0*x + 3.0*y + 0.2*y*y + 0.1*x*y + 0.2*math.Sqrt(math.Abs(x))
	ret += (20.0*math.Sin(6.0*x*math.Pi) + 20.0*math.Sin(2.0*x*math.Pi)) * 2.0 / 3.0
	ret += (20.0*math.Sin(y*math.Pi) + 40.0*math.Sin(y/3.0*math.Pi)) * 2.0 / 3.0
	ret += (160.0*math.Sin(y/12.0*math.Pi) + 320*math.Sin(y*math.Pi/30.0)) * 2.0 / 3.0
	return ret
}

func transformLng(x, y float64) float64 {
	ret := 300.0 + x + 2.0*y + 0.1*x*x + 0.1*x*y + 0.1*math.Sqrt(math.Abs(x))
	ret += (20.0*math.Sin(6.0*x*math.Pi) + 20.0*math.Sin(2.0*x*math.Pi)) * 2.0 / 3.0
	ret += (20.0*math.Sin(x*math.Pi) + 40.0*math.Sin(x/3.0*math.Pi)) * 2.0 / 3.0
	ret += (150.0*math.Sin(x/12.0*math.Pi) + 300.0*math.Sin(x/30.0*math.Pi)) * 2.0 / 3.0
	return ret
}

func delta(lng, lat float64) (float64, float64) {
	dLat := transformLat(lng-105.0, lat-35.0)
	dLng := transformLng(lng-105.0, lat-35.0)
	radLat := lat / 180.0 * math.Pi
	magic := math.Sin(radLat)
	magic = 1 - gcjEE*magic*magic
	sqrtMagic := math.Sqrt(magic)
	dLat = dLat * 180.0 / ((gcjA * (1 - gcjEE)) / (magic * sqrtMagic) * math.Pi)
	dLng = dLng * 180.0 / (gcjA / sqrtMagic * math.Cos(radLat) * math.Pi)
	return dLng, dLat
}

// WGS84ToGCJ02 converts WGS-84 to GCJ-02. Longitude first, both in and out.
func WGS84ToGCJ02(lng, lat float64) (float64, float64) {
	if outOfChina(lng, lat) {
		return lng, lat
	}
	dLng, dLat := delta(lng, lat)
	return lng + dLng, lat + dLat
}

// GCJ02ToWGS84 converts GCJ-02 to WGS-84. A single-step inverse, so the round
// trip loses a few metres.
func GCJ02ToWGS84(lng, lat float64) (float64, float64) {
	if outOfChina(lng, lat) {
		return lng, lat
	}
	dLng, dLat := delta(lng, lat)
	return lng - dLng, lat - dLat
}

// GCJ02ToBD09 converts GCJ-02 to BD-09.
func GCJ02ToBD09(lng, lat float64) (float64, float64) {
	z := math.Sqrt(lng*lng+lat*lat) + 0.00002*math.Sin(lat*xPi)
	theta := math.Atan2(lat, lng) + 0.000003*math.Cos(lng*xPi)
	return z*math.Cos(theta) + 0.0065, z*math.Sin(theta) + 0.006
}

// BD09ToGCJ02 converts BD-09 to GCJ-02.
func BD09ToGCJ02(lng, lat float64) (float64, float64) {
	x := lng - 0.0065
	y := lat - 0.006
	z := math.Sqrt(x*x+y*y) - 0.00002*math.Sin(y*xPi)
	theta := math.Atan2(y, x) - 0.000003*math.Cos(x*xPi)
	return z * math.Cos(theta), z * math.Sin(theta)
}

// WGS84ToBD09 converts WGS-84 to BD-09.
func WGS84ToBD09(lng, lat float64) (float64, float64) {
	gLng, gLat := WGS84ToGCJ02(lng, lat)
	return GCJ02ToBD09(gLng, gLat)
}

// BD09ToWGS84 converts BD-09 to WGS-84.
func BD09ToWGS84(lng, lat float64) (float64, float64) {
	gLng, gLat := BD09ToGCJ02(lng, lat)
	return GCJ02ToWGS84(gLng, gLat)
}

// Distance returns the great-circle distance in kilometres.
// Latitude first, unlike the conversions above.
func Distance(lat1, lng1, lat2, lng2 float64) float64 {
	toRad := func(deg float64) float64 { return deg * math.Pi / 180.0 }
	dLat := toRad(lat2 - lat1)
	dLng := toRad(lng2 - lng1)
	a := math.Pow(math.Sin(dLat/2), 2) +
		math.Cos(toRad(lat1))*math.Cos(toRad(lat2))*math.Pow(math.Sin(dLng/2), 2)
	return 2 * earthRadiusKm * math.Asin(math.Min(1, math.Sqrt(a)))
}
