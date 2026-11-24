# Security

## Reporting a vulnerability
Report it privately through GitHub: open the repository's **Security** tab and choose **Report a vulnerability**. Please don't open a public issue for a security problem. Include what you found, how to reproduce it, and the commit you tested.

labelqueue is a side project maintained by one person. Reports are answered as time allows, usually within a week. There is no bug bounty.

## How labelqueue is meant to be run
The API has **no authentication**: anyone who can reach port 8000 can print, read job history and previews, and make the server fetch an image from any `http(s)` URL. Run it on a trusted LAN, or behind a reverse proxy that adds authentication. Never expose it directly to the internet.
