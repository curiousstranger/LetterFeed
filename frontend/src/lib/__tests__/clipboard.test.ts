import { copyText } from "../clipboard"

describe("copyText", () => {
  const originalClipboard = navigator.clipboard

  afterEach(() => {
    Object.defineProperty(navigator, "clipboard", {
      value: originalClipboard,
      configurable: true,
      writable: true,
    })
    // @ts-expect-error jsdom does not implement execCommand
    delete document.execCommand
  })

  const setClipboard = (value: unknown) => {
    Object.defineProperty(navigator, "clipboard", {
      value,
      configurable: true,
      writable: true,
    })
  }

  it("uses the async clipboard API when it is available", async () => {
    const writeText = jest.fn().mockResolvedValue(undefined)
    setClipboard({ writeText })

    await expect(copyText("hello")).resolves.toBe(true)
    expect(writeText).toHaveBeenCalledWith("hello")
  })

  it("falls back to execCommand when the clipboard API is missing", async () => {
    // What an http:// deployment actually looks like: no secure context, so the
    // browser does not expose navigator.clipboard at all.
    setClipboard(undefined)
    const execCommand = jest.fn(() => true)
    // @ts-expect-error jsdom does not implement execCommand
    document.execCommand = execCommand

    await expect(copyText("hello")).resolves.toBe(true)
    expect(execCommand).toHaveBeenCalledWith("copy")
    expect(document.querySelector("textarea")).toBeNull()
  })

  it("falls back to execCommand when the clipboard API rejects", async () => {
    setClipboard({ writeText: jest.fn().mockRejectedValue(new Error("denied")) })
    const execCommand = jest.fn(() => true)
    // @ts-expect-error jsdom does not implement execCommand
    document.execCommand = execCommand

    await expect(copyText("hello")).resolves.toBe(true)
    expect(execCommand).toHaveBeenCalledWith("copy")
  })

  it("reports failure instead of throwing when nothing works", async () => {
    setClipboard(undefined)
    // @ts-expect-error jsdom does not implement execCommand
    document.execCommand = jest.fn(() => false)

    await expect(copyText("hello")).resolves.toBe(false)
  })
})
