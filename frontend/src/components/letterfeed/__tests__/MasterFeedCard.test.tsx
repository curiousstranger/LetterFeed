import React from "react"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import "@testing-library/jest-dom"
import { MasterFeedCard } from "../MasterFeedCard"
import { exportOpml, getOpmlSubscribeUrl, rotateOpmlSubscribeUrl } from "@/lib/api"

// Mock the api functions used by the card
jest.mock("@/lib/api", () => ({
  ...jest.requireActual("@/lib/api"),
  getMasterFeedUrl: jest.fn(() => "http://mock-api/feeds/all"),
  exportOpml: jest.fn(),
  getOpmlSubscribeUrl: jest.fn(),
  rotateOpmlSubscribeUrl: jest.fn(),
}))

// Mock the toast
jest.mock("sonner", () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}))

// Mock navigator.clipboard
Object.assign(navigator, {
  clipboard: {
    writeText: jest.fn(),
  },
})

const SUB_URL = "http://mock-api/api/feeds/opml/key-one"

describe("MasterFeedCard", () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(getOpmlSubscribeUrl as jest.Mock).mockResolvedValue({ url: SUB_URL })
  })

  it("renders the master feed card with the correct URL", () => {
    render(<MasterFeedCard />)

    expect(screen.getByText("Master Feed")).toBeInTheDocument()
    expect(
      screen.getByText(
        "This feed contains all entries from all your newsletters in one place."
      )
    ).toBeInTheDocument()

    const feedLink = screen.getByRole("link")
    expect(feedLink).toHaveAttribute("href", "http://mock-api/feeds/all")
    expect(feedLink).toHaveTextContent("http://mock-api/feeds/all")
  })

  it("downloads the OPML export as letterfeed.opml", async () => {
    const blob = new Blob(["<opml/>"], { type: "text/x-opml" })
    ;(exportOpml as jest.Mock).mockResolvedValueOnce(blob)
    const createObjectURL = jest.fn(() => "blob:mock-url")
    const revokeObjectURL = jest.fn()
    Object.assign(URL, { createObjectURL, revokeObjectURL })
    const clickSpy = jest
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        expect(this.href).toBe("blob:mock-url")
        expect(this.download).toBe("letterfeed.opml")
      })

    render(<MasterFeedCard />)
    await userEvent.click(screen.getByRole("button", { name: /export opml/i }))

    await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(1))
    expect(exportOpml).toHaveBeenCalledTimes(1)
    expect(createObjectURL).toHaveBeenCalledWith(blob)
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-url")
    clickSpy.mockRestore()
  })
  it("shows the subscription URL as copyable text rather than a link", async () => {
    render(<MasterFeedCard />)

    expect(await screen.findByText(SUB_URL)).toBeInTheDocument()
    // Exactly one link on the card: the RSS feed URL. A key in an anchor would
    // end up in browser history.
    expect(screen.getAllByRole("link")).toHaveLength(1)
    expect(screen.queryByRole("link", { name: SUB_URL })).not.toBeInTheDocument()
  })

  it("copies the subscription URL to the clipboard", async () => {
    render(<MasterFeedCard />)
    await screen.findByText(SUB_URL)

    await userEvent.click(screen.getByRole("button", { name: /copy/i }))

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(SUB_URL)
  })

  it("regenerates the URL after confirmation and shows the new one", async () => {
    ;(rotateOpmlSubscribeUrl as jest.Mock).mockResolvedValue({
      url: "http://mock-api/api/feeds/opml/key-two",
    })
    jest.spyOn(window, "confirm").mockReturnValue(true)

    render(<MasterFeedCard />)
    await screen.findByText(SUB_URL)
    await userEvent.click(screen.getByRole("button", { name: /regenerate/i }))

    expect(
      await screen.findByText("http://mock-api/api/feeds/opml/key-two")
    ).toBeInTheDocument()
    expect(screen.queryByText(SUB_URL)).not.toBeInTheDocument()
  })

  it("does not regenerate when the confirmation is declined", async () => {
    jest.spyOn(window, "confirm").mockReturnValue(false)

    render(<MasterFeedCard />)
    await screen.findByText(SUB_URL)
    await userEvent.click(screen.getByRole("button", { name: /regenerate/i }))

    expect(rotateOpmlSubscribeUrl).not.toHaveBeenCalled()
    expect(screen.getByText(SUB_URL)).toBeInTheDocument()
  })
})
