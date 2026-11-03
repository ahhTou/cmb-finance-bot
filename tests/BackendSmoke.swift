import Foundation

@main struct BackendSmoke {
    static func main() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root.appendingPathComponent("src"), withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let fixture = """
        import sys, json
        command = sys.argv[1]
        if command == 'status':
            sys.stderr.write('diagnostic' * 20000)
            print(json.dumps({'ok': True, 'phase': 'armed'}))
        elif command == 'stdin':
            data = json.load(sys.stdin)
            assert data == {'new': 'test-only-value'}
            assert 'test-only-value' not in sys.argv
            print(json.dumps({'ok': True}))
        else:
            print(json.dumps({'ok': False, 'error': '模拟拒绝'}))
            sys.exit(1)
        """
        try fixture.write(to: root.appendingPathComponent("src/admin_cli.py"), atomically: true, encoding: .utf8)
        let backend = Backend(root: root.path, python: "/usr/bin/python3")
        let state = try await backend.run(["status"])
        precondition(state["phase"] as? String == "armed")
        let input = try await backend.run(["stdin"], input: ["new": "test-only-value"])
        precondition(input["ok"] as? Bool == true)
        do {
            _ = try await backend.run(["refuse"])
            fatalError("Nonzero exit must throw")
        } catch {
            precondition(error.localizedDescription == "模拟拒绝")
        }
        print("Backend smoke: JSON, stdin, large stderr, and refusal passed")
    }
}
