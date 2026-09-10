package geotoolcn

// Administrative hierarchy rules. SPEC.md §1.4.

// mergedPrefixes are the municipalities (直辖市) and SARs (特别行政区): their
// districts sit directly under the province and the city node reuses the
// province code.
var mergedPrefixes = map[string]bool{
	"11": true, "12": true, "31": true, "50": true, "81": true, "82": true,
}

// parentCityCode resolves a district's parent city adcode, or "" if none.
//
// adcode[:4] + "00" looks like the rule and is wrong for the 30 province-
// directly-governed county-level divisions (省直辖县级行政区) in adcode blocks
// 4190, 4290, 4690 and 6590: it produces codes such as 419000 that name no real
// division. Those appear in the city layer under their own code.
func parentCityCode(districtCode string, cityCodes map[string]bool) string {
	prefix2 := districtCode[:2]
	if mergedPrefixes[prefix2] {
		return prefix2 + "0000"
	}
	byPrefix := districtCode[:4] + "00"
	if cityCodes[byPrefix] {
		return byPrefix
	}
	if cityCodes[districtCode] {
		return districtCode
	}
	return ""
}
