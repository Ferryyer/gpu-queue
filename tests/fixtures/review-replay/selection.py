def select(rows, window, limit):
    selected = []
    for row in sorted(rows, key=lambda row: (row["due"], row["ticket"])):
        if row["due"] > window:
            break
        selected.append(row)
    return selected[:limit]
