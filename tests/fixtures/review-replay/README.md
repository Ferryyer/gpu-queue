# Sample handout planning

`select(rows, window, limit)` selects rows due at or before the requested window. Return up to `limit` eligible rows, ordered by due window and then ticket ID. Each ticket is a distinct handout even when display labels coincide. Rows contain synthetic integer ticket and due fields and a plain text label. A zero limit returns an empty list.
