// Name tag core. Included by a generated wrapper:
//
//   use <fonts/ttf/<font>.ttf>
//   use <shapes/<id>/shape.scad>     // outline(tw, th), hole_pos(tw, th); may read $hole
//   include <lib/tag.scad>
//
// All layout numbers are computed by the backend (nametag/render.py layout())
// and passed with -D; the print geometry comes from config/print.json.
// Units mm, Z up, base at Z=0. Shapes are designed in "design units" and
// scaled by s * k; the keyring hole keeps its absolute size.
//
// No 3D booleans: base and text are separate linear_extrudes (no CGAL);
// part="base"/"text" exports one of them, the backend joins the meshes. The
// text sinks text_overlap into the base so the slicer unions them.

/* [Layout, from the backend] */
name = "NAME";
font = "Baloo 2:style=Bold";
size = 10;            // font size in design units
tx = 0;               // centres the text bbox at the origin (text frame)
ty = 0;
rot = 0;              // text rotation, 90 = vertical, reads bottom to top
cx = 0;               // text box centre on the tag (design units, incl. k)
cy = 0;
tw = 40;              // text bbox on the tag (design units), for "grow" shapes
th = 10;
k = 1;                // outline scale of "fit" shapes, 1 for "grow" shapes
part = "all";         // all | base | text | outline2d | text2d | measure2d

/* [Print geometry, from config/print.json] */
s = 1;                // global scale (smaller tags for a finer nozzle)
base_h = 2.4;         // base plate thickness (same for all shapes -> one M600 layer)
text_h = 1.2;         // text height above the base
text_overlap = 0.2;   // text sinks this far into the base (one layer)
text_grow = 0;        // offset of the glyph outlines, mm (thin fonts)
hole_d = 4.5;         // keyring hole, absolute mm

$fn = 48;

assert(len(name) > 0, "empty name");
assert(k >= 1, "k must be >= 1");

module raw_text() {
    text(name, size = size, font = font, halign = "left", valign = "baseline");
}

module tag_text_2d() {
    offset(delta = text_grow)
        scale(s) translate([cx, cy]) rotate(rot) translate([tx, ty]) raw_text();
}

// Shapes see the hole diameter in design units as $hole (dynamic scope).
module tag_base_2d() {
    $hole = hole_d / (s * k);
    difference() {
        scale(s * k) outline(tw / k, th / k);
        translate(s * k * hole_pos(tw / k, th / k)) circle(d = hole_d);
    }
}

if (part == "all" || part == "base")
    color("RoyalBlue") linear_extrude(base_h) tag_base_2d();

if (part == "all" || part == "text")
    color("Red") translate([0, 0, base_h - text_overlap])
        linear_extrude(text_h + text_overlap) tag_text_2d();

if (part == "outline2d") tag_base_2d();
if (part == "text2d") tag_text_2d();
if (part == "measure2d") raw_text();       // unplaced, for measuring
