// Wavy ribbon: a bar like "stadium" whose top and bottom edges follow the same
// sine wave, so it looks like a waving band. Grows with the name, hole on the left.
// "grow" shape: outline(tw, th) gets the text bbox (centred at origin).
pad_x = 4;          // text to the right end
pad_y = 3.5;        // text to the edge at a wave trough
amp = 2.2;          // wave amplitude
period = 34;        // wave length (one long swing reads as a ribbon, short ones look frilly)
min_h = 20;         // minimum band height (edge to edge, vertical)
min_len = 50;       // minimum overall length (short names)
hole_space = 9;     // extra length on the left for the hole
hole_wall = 3;      // material between hole and left edge
round_r = 3.5;      // rounding of the four corners

function band_h(th) = max(min_h, th + 2 * pad_y + 2 * amp);
function body_w(tw) = max(tw + 2 * pad_x, min_len - hole_space);
function bar_left(tw) = -body_w(tw) / 2 - hole_space;
function bar_right(tw) = body_w(tw) / 2;
// wave centred on the text: zero crossing at x = 0, so short and long names look alike
function wave(x) = amp * sin(360 * x / period);

module outline(tw, th) {
    l = bar_left(tw); r = bar_right(tw); h = band_h(th) / 2;
    n = max(8, ceil((r - l) / 1));
    top = [for (i = [0:n]) let(x = l + (r - l) * i / n) [x, h + wave(x)]];
    bot = [for (i = [n:-1:0]) let(x = l + (r - l) * i / n) [x, -h + wave(x)]];
    offset(r = round_r) offset(delta = -round_r) polygon(concat(top, bot));
}

function hole_pos(tw, th) = let(x = bar_left(tw) + hole_wall + $hole / 2) [x, wave(x)];   // $hole from lib/tag.scad
