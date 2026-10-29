import Foundation
import ImageIO
import Vision

// Local-only verification: the URL's date is not proof of the printed date.
// Build this helper into the app; employees do not need Swift or Xcode.
guard CommandLine.arguments.count == 3 else { exit(64) }
let url = URL(fileURLWithPath: CommandLine.arguments[1])
let expected = CommandLine.arguments[2].split(separator: "-").compactMap { Int($0) }
guard expected.count == 3, (1...12).contains(expected[1]), (1...31).contains(expected[2]),
      let source = CGImageSourceCreateWithURL(url as CFURL, nil),
      CGImageSourceGetType(source) as String? == "public.jpeg",
      let image = CGImageSourceCreateImageAtIndex(source, 0, nil),
      (200...4000).contains(image.width), (300...6000).contains(image.height) else { exit(65) }

do {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = false
    try VNImageRequestHandler(cgImage: image).perform([request])
    let results = request.results ?? []
    let months = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二"]
    let month = months[expected[1] - 1] + "月"
    let hasMonth = results.contains { item in
        item.boundingBox.midY > 0.85 &&
        item.topCandidates(1).first?.string.replacingOccurrences(of: " ", with: "") == month
    }
    let hasDay = results.contains { item in
        item.boundingBox.height > 0.12 && (0.35...0.8).contains(item.boundingBox.midY) &&
        Int(item.topCandidates(1).first?.string ?? "") == expected[2]
    }
    let hasYear = results.contains { item in
        item.boundingBox.midY < 0.15 &&
        (item.topCandidates(1).first?.string.contains(String(expected[0])) ?? false)
    }
    guard hasMonth && hasDay && hasYear else { exit(66) }
    print(CommandLine.arguments[2])
} catch {
    exit(65)
}
