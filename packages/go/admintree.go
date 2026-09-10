package geotoolcn

// Province → city → district tree. SPEC.md §2.10.
//
// Needs no geometry, so it works from the mini dataset too.

import (
	_ "embed"
	"encoding/json"
	"sort"
	"sync"
)

//go:embed data/china_admin.json
var embeddedAdmin []byte

// TreeNode is one node of the administrative tree.
//
// Children is nil on leaves (districts) and non-nil, though possibly empty, on
// province and city nodes — 台湾省 has no sub-divisions in the source data but
// is still a province. MarshalJSON preserves that distinction: a leaf omits the
// key entirely, a childless province emits "children":[]. Collapsing the two
// changes the tree hash the conformance suite pins.
type TreeNode struct {
	Value    string      `json:"value"`
	Label    string      `json:"label"`
	Children []*TreeNode `json:"children,omitempty"`
}

// MarshalJSON emits "children" exactly when the node is not a leaf.
func (n *TreeNode) MarshalJSON() ([]byte, error) {
	if n.Children == nil {
		return json.Marshal(struct {
			Value string `json:"value"`
			Label string `json:"label"`
		}{n.Value, n.Label})
	}
	return json.Marshal(struct {
		Value    string      `json:"value"`
		Label    string      `json:"label"`
		Children []*TreeNode `json:"children"`
	}{n.Value, n.Label, n.Children})
}

type adminData struct {
	Provinces [][2]string `json:"provinces"`
	Cities    [][2]string `json:"cities"`
	Districts [][2]string `json:"districts"`
}

var (
	treeOnce sync.Once
	treeVal  []*TreeNode
	treeErr  error
)

// GetAdministrativeTree returns the three-level tree, built once and reused.
func GetAdministrativeTree() ([]*TreeNode, error) {
	treeOnce.Do(func() { treeVal, treeErr = buildTree() })
	return treeVal, treeErr
}

func buildTree() ([]*TreeNode, error) {
	var raw adminData
	if err := json.Unmarshal(embeddedAdmin, &raw); err != nil {
		return nil, err
	}

	provinceNames := make(map[string]string, len(raw.Provinces))
	provinceCodes := make([]string, 0, len(raw.Provinces))
	for _, p := range raw.Provinces {
		provinceNames[p[0]] = p[1]
		provinceCodes = append(provinceCodes, p[0])
	}
	sort.Strings(provinceCodes)

	cityCodes := make(map[string]bool, len(raw.Cities))
	for _, c := range raw.Cities {
		cityCodes[c[0]] = true
	}

	// Attach each district to the city the hierarchy rules name as its parent.
	// Grouping by 4-digit prefix instead places every province-directly-governed
	// county-level division under all of its siblings, since they share a prefix.
	districtsByParent := map[string][][2]string{}
	for _, d := range raw.Districts {
		if parent := parentCityCode(d[0], cityCodes); parent != "" {
			districtsByParent[parent] = append(districtsByParent[parent], d)
		}
	}
	citiesByProvince := map[string][][2]string{}
	for _, c := range raw.Cities {
		prefix2 := c[0][:2]
		citiesByProvince[prefix2] = append(citiesByProvince[prefix2], c)
	}

	byCode := func(pairs [][2]string) {
		sort.Slice(pairs, func(i, j int) bool { return pairs[i][0] < pairs[j][0] })
	}
	leaves := func(pairs [][2]string) []*TreeNode {
		byCode(pairs)
		out := make([]*TreeNode, 0, len(pairs))
		for _, p := range pairs {
			out = append(out, &TreeNode{Value: p[0], Label: p[1]})
		}
		return out
	}

	tree := make([]*TreeNode, 0, len(provinceCodes))
	for _, provinceCode := range provinceCodes {
		prefix2 := provinceCode[:2]
		label := provinceNames[provinceCode]
		// Non-nil so a childless province still serialises "children":[].
		children := []*TreeNode{}

		if mergedPrefixes[prefix2] {
			// Municipality / SAR: one city node whose value is the province code.
			children = append(children, &TreeNode{
				Value:    provinceCode,
				Label:    label,
				Children: leaves(districtsByParent[provinceCode]),
			})
		} else {
			cities := citiesByProvince[prefix2]
			byCode(cities)
			for _, c := range cities {
				children = append(children, &TreeNode{
					Value:    c[0],
					Label:    c[1],
					Children: leaves(districtsByParent[c[0]]),
				})
			}
		}
		tree = append(tree, &TreeNode{Value: provinceCode, Label: label, Children: children})
	}
	return tree, nil
}
