"use client"

import { useCallback, useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Rss, ExternalLink, Download, Copy, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import {
  exportOpml,
  getMasterFeedUrl,
  getOpmlSubscribeUrl,
  rotateOpmlSubscribeUrl,
} from "@/lib/api"

export function MasterFeedCard() {
  const feedUrl = getMasterFeedUrl()
  const [subscribeUrl, setSubscribeUrl] = useState<string | null>(null)

  useEffect(() => {
    getOpmlSubscribeUrl()
      .then(({ url }) => setSubscribeUrl(url))
      .catch(() => {
        // getOpmlSubscribeUrl already reported the error
      })
  }, [])

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

  const handleCopy = useCallback(async () => {
    if (!subscribeUrl) return
    await navigator.clipboard.writeText(subscribeUrl)
    toast.success("Subscription URL copied")
  }, [subscribeUrl])

  const handleRegenerate = async () => {
    const confirmed = window.confirm(
      "Regenerate the subscription URL? The current URL stops working, and any reader using it will need the new one."
    )
    if (!confirmed) return
    try {
      const { url } = await rotateOpmlSubscribeUrl()
      setSubscribeUrl(url)
      toast.success("New subscription URL generated")
    } catch {
      // rotateOpmlSubscribeUrl already reported the error
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
          <h4 className="text-sm font-medium text-gray-700 mb-2">
            OPML subscription list
          </h4>
          <p className="text-sm text-muted-foreground mb-2">
            Download the list for a one-off import, or give a reader the URL to follow
            it. FreshRSS reads it as a category&apos;s dynamic OPML, subscribing to new
            newsletters as they appear.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" onClick={handleExportOpml}>
              <Download className="w-4 h-4" />
              Export OPML
            </Button>
            {subscribeUrl && (
              <>
                <Button variant="outline" size="sm" onClick={handleCopy}>
                  <Copy className="w-4 h-4" />
                  Copy subscription URL
                </Button>
                <Button variant="ghost" size="sm" onClick={handleRegenerate}>
                  <RefreshCw className="w-4 h-4" />
                  Regenerate
                </Button>
              </>
            )}
          </div>
          {subscribeUrl && (
            <>
              <code className="mt-2 block break-all rounded bg-muted px-2 py-1 text-xs text-muted-foreground">
                {subscribeUrl}
              </code>
              <p className="text-xs text-muted-foreground mt-2">
                This URL works without logging in, so anyone who has it can read your
                newsletter list and feeds. Regenerate it if it leaks.
              </p>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
