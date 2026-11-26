import XCTest
@testable import Hello

final class HelloTests: XCTestCase {
    func testGreeting() {
        XCTAssertEqual(greeting("lab"), "Hello, lab!")
    }
}
