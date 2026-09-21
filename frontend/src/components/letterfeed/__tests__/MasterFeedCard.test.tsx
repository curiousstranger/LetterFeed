import React from "react"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import "@testing-library/jest-dom"
import { MasterFeedCard } from "../MasterFeedCard"
import { exportOpml } from "@/lib/api"

// Mock the api functions used by the card
jest.mock("@/lib/api", () => ({
  ...jest.requireActual("@/lib/api"),
  getMasterFeedUrl: jest.fn(() => "http://mock-api/feeds/all"),
  exportOpml: jest.fn(),
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

describe("MasterFeedCard", () => {
  beforeEach(() => {
    jest.clearAllMocks()
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
})
