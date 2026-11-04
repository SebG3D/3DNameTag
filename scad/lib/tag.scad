// Name tag core. Included by a generated wrapper:
//
//   use <fonts/ttf/<font>.ttf>
//   use <shapes/<id>/shape.scad>     // outline(tw, th), hole_pos(tw, th)
//   include <lib/tag.scad>
//
// All layout numbers (text size, offset, k) are computed by the backend
// (nametag/layout.py) and passed with -D. Units mm, Z up, base at Z=0,
// text block centred at the origin (XY).
//
// Rendering avoids 3D booleans: base and text are separate linear_extrudes
// (no CGAL), part="base"/"text" exports one of them. The backend joins the two
// meshes; the text sinks text_overlap into the base so the slicer unions them.

/* [Input] */
name = "NAME";
font = "Baloo 2:style=Bold";
size = 10;            // font size passed to text()
tx = 0;               // text translation so its bbox is centred at origin
ty = 0;
tw = 40;              // final text bbox width  (for "grow" shapes)
th = 10;              // final text bbox height (for "grow" shapes)
k = 1;                // outline scale ("fit" shapes), 1 for "grow" shapes
part = "all";         // all | base | text

/* [Fixed geometry, same for every shape so M600 is at one layer] */
base_h = 2.4;         // base plate thickness
text_h = 1.2;         // text height above the base
text_overlap = 0.2;   // text sinks this far into the base (one layer)
text_grow = 0;        // offset of the glyph outlines (thin fonts), mm
hole_d = 4.5;         // keyring hole diameter, not scaled with k

$fn = 48;

assert(len(name) > 0, "empty name");
assert(k >= 1, "k must be >= 1");

module tag_text_2d() {
    offset(delta = text_grow)
        translate([tx, ty])
            text(name, size = size, font = font, halign = "left", valign = "baseline");
}

module tag_base_2d() {
    difference() {
        scale(k) outline(tw / k, th / k);
        translate(k * hole_pos(tw / k, th / k)) circle(d = hole_d);
    }
}

if (part == "all" || part == "base")
    color("RoyalBlue") linear_extrude(base_h) tag_base_2d();

if (part == "all" || part == "text")
    color("Red") translate([0, 0, base_h - text_overlap])
        linear_extrude(text_h + text_overlap) tag_text_2d();

if (part == "outline2d") tag_base_2d();     // for icons / checks
if (part == "text2d") tag_text_2d();        // for measuring / UI preview

echo(str("TAG name=", name, " k=", k, " size=", size, " base_h=", base_h, " text_top=", base_h + text_h));
