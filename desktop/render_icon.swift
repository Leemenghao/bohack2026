import AppKit

// Editable vector drawing for the LuLu app icon.
let size = 1024
let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
                             bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                             isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
NSColor(srgbRed: 0.96, green: 0.94, blue: 0.89, alpha: 1).setFill()
NSBezierPath(roundedRect: NSRect(x: 64, y: 64, width: 896, height: 896), xRadius: 210, yRadius: 210).fill()
NSColor(srgbRed: 0.24, green: 0.43, blue: 0.36, alpha: 1).setStroke()
for x in [310.0, 590.0] {
    let path = NSBezierPath()
    path.lineWidth = 100
    path.lineCapStyle = .round
    path.lineJoinStyle = .round
    path.move(to: NSPoint(x: x, y: 680))
    path.line(to: NSPoint(x: x, y: 400))
    path.curve(to: NSPoint(x: x + 100, y: 320),
               controlPoint1: NSPoint(x: x, y: 330),
               controlPoint2: NSPoint(x: x + 30, y: 320))
    path.line(to: NSPoint(x: x + 130, y: 320))
    path.stroke()
}
NSColor(srgbRed: 0.62, green: 0.75, blue: 0.64, alpha: 1).setFill()
NSBezierPath(ovalIn: NSRect(x: 714, y: 646, width: 68, height: 68)).fill()
NSGraphicsContext.restoreGraphicsState()
try bitmap.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
