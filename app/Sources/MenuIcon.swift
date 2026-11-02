import AppKit

enum MenuIcon {
    private static let akemi = [
        "........#####.......",
        "......########......",
        "......########......",
        ".....##..##..##.....",
        ".....##..##..##.....",
        ".....##..##..##.....",
        ".....##########.....",
        ".....##########.....",
        ".....##########.....",
        "##...##########...##",
        ".##..##########..##.",
        "..###..........###..",
        "...###........###...",
        "........#..#........",
        "........#..#........",
        "........#..#........",
        "........#..#........",
    ]

    static func image() -> NSImage {
        let cell: CGFloat = 1.05
        let size = NSSize(width: CGFloat(akemi[0].count) * cell,
                          height: CGFloat(akemi.count) * cell)

        let image = NSImage(size: size, flipped: true) { _ in
            NSColor.black.setFill()
            for (line, row) in akemi.enumerated() {
                for (column, mark) in row.enumerated() where mark == "#" {
                    NSBezierPath(rect: NSRect(x: CGFloat(column) * cell,
                                              y: CGFloat(line) * cell,
                                              width: cell, height: cell)).fill()
                }
            }
            return true
        }
        image.isTemplate = true
        return image
    }
}
