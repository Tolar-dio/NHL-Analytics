# NHL proxy

A read-only Vercel edge function that relays a few public NHL endpoints (`score/now`, `score/<date>`,
`gamecenter/<id>/{play-by-play,landing,boxscore}`) with CORS headers for Read the Ice's live pages, cached at the
edge for 15 to 60 seconds. Deployed as the Vercel project `readtheice-api`: `https://<deployment>/api/nhl?path=score/now`.
