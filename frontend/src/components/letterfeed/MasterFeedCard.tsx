"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Rss, ExternalLink, Download } from "lucide-react"
import { exportOpml, getMasterFeedUrl } from "@/lib/api"

export function MasterFeedCard() {
  const feedUrl = getMasterFeedUrl()

  const handleExportOpml = async () => {
    try {
      const blob = await exportOpml()
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = "letterfeed.opml"
      link.click()
      URL.revokeObjectURL(url)
    } catch {
      // exportOpml already reported the error
    }
  }

  return (
    <Card className="mb-8">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Rss className="w-5 h-5 text-orange-500" />
          Master Feed
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          This feed contains all entries from all your newsletters in one place.
        </p>
        <div>
          <h4 className="text-sm font-medium text-gray-700 mb-2">RSS Feed URL</h4>
          <div className="flex items-center gap-2">
            <a
              href={feedUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800 hover:underline"
            >
              <ExternalLink className="w-3 h-3" />
              {feedUrl}
            </a>
          </div>
        </div>
        <div>
          <Button variant="outline" size="sm" onClick={handleExportOpml}>
            <Download className="w-4 h-4" />
            Export OPML
          </Button>
          <p className="text-xs text-muted-foreground mt-2">
            Download every active newsletter feed as an OPML file for your feed reader.
          </p>
        </div>
      </CardContent>
    </Card>
  )
}
