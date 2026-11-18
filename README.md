# A Bouquet That Blooms for You

A digital bouquet for Jane. It opens in darkness, a single rose blooms under a spotlight, and then the rest of the bouquet grows around it. When the animation ends she can turn it, zoom in, and tap any flower to read a note.

```
bouquet/
├── web/
│   ├── index.html              ← the whole interactive experience (Three.js)
│   ├── bouquet.glb             ← Blender-built bouquet, animated, Draco-compressed (3.9 MB)
│   ├── bouquet_cinematic.mp4   ← fallback film for devices without WebGL
│   └── vercel.json             ← hosting settings (caching)
├── blender/
│   └── bouquet.py              ← procedural bouquet + animation + Cycles render + GLB export
├── build_web.sh                ← Blender → GLB → compressed GLB → web/
└── README.md
```

---

## 1. Make it yours (2 minutes)

Open `web/index.html`. The `CONFIG` block at the top of the script holds every line of text:

```js
const CONFIG = {
  to: 'Jane',
  opening:   'Jane, I wanted to give you flowers…',
  reveal:    'I’m sorry I don’t give you enough flowers.<br>’Til the day comes when I can buy you a whole garden, these are for you…',
  signature: 'With love, Curtis <span class="heart">❤️</span>',
  heroMessage: 'This rose opened first. It was always going to be for you.',
  messages: [ … 12 short notes … ],
```

The `messages` are the notes that appear when she taps a flower. Each tap shows a different one until all of them have appeared. The placeholder notes are warm but generic. Replace a few with things only you would say, like an inside joke, a place you've been together, or a date. Those are the ones that will mean the most to her.

In the Blender film, the same lines live at the top of `blender/bouquet.py` (`LINE_OPENING`, …).

---

## 2. Generate the bouquet in Blender

You need **Blender 4.2 LTS or newer** (tested on 5.3), from <https://www.blender.org/download/>.

### Look at it / tweak it by hand
Open Blender, go to **Scripting** and **Open** `blender/bouquet.py`, then click **▶ Run Script**. This builds the whole scene: about 3,000 objects, the lights, the camera moves and the titles. Press **Space** in the timeline to watch the bloom, and switch the viewport to *Rendered* to see it in Cycles.

### From a terminal

```bash
# Windows:  "C:\Program Files\Blender Foundation\Blender 4.2\blender.exe"
# macOS:    /Applications/Blender.app/Contents/MacOS/Blender
BLENDER=blender

# a single preview frame (seconds into the film, or F<frame>)
$BLENDER --background --python blender/bouquet.py -- --still 22 --quality preview

# keep a .blend to open later
$BLENDER --background --python blender/bouquet.py -- --save
```

Useful flags: `--seed 7` (a different arrangement), `--no-volume` (skips the haze and renders much faster), and `--font path/to/CormorantGaramond-LightItalic.ttf` (elegant titles; the font is free from Google Fonts).

### Export the web asset

```bash
./build_web.sh            # or follow the two steps inside it by hand
```

This runs Blender with `--glb`, a lighter web build where each hydrangea head is merged into one mesh. Then [`gltf-transform`](https://gltf-transform.dev) applies Draco and WebP compression (37 MB → about 4 MB) and copies the result to `web/bouquet.glb`. The page uses `bouquet.glb` automatically when it is next to `index.html`. If the file is missing, the page grows the same bouquet procedurally in the browser, so it works either way.

---

## 3. Render the cinematic film in Cycles (optional, best quality)

```bash
$BLENDER --background --python blender/bouquet.py -- --anim --quality final --font CormorantGaramond-LightItalic.ttf
ffmpeg -framerate 30 -i blender/out/frames/frame_%04d.png \
       -c:v libx264 -pix_fmt yuv420p -crf 17 -preset slow -movflags +faststart \
       web/bouquet_cinematic.mp4
```

* The film is 28 s at 30 fps (841 frames), 1920×1080, with 384 samples, OpenImageDenoise, subsurface-scattering petals, volumetric haze and depth of field.
* With a recent NVIDIA or AMD GPU, or on Apple Silicon, expect roughly 20–60 s per frame. The script picks OptiX, CUDA, HIP or Metal automatically. On a CPU it takes much longer, so try `--no-volume --quality preview` first.
* Frames are written one by one as PNGs, so you can stop and resume the render. To resume, set the frame range in the saved `.blend` and render from there.

The included `bouquet_cinematic.mp4` was captured from the web renderer so the fallback works right away. Replace it with your Cycles render whenever you like.

---

## 4. Put it online with Vercel (free, about 5 minutes)

The `web/` folder is the whole site: `index.html`, `bouquet.glb`, `bouquet_cinematic.mp4`, and `vercel.json`. It's plain static files, so there is no build step.

**Option A: Vercel CLI (fastest)**
1. Install Node.js from <https://nodejs.org> if you don't have it.
2. In a terminal:
   ```bash
   npm i -g vercel
   cd bouquet/web
   vercel            # log in, accept the defaults; "Other" framework, no build command
   vercel --prod     # publishes the real link
   ```
3. You get a link like `https://for-jane.vercel.app`. To rename it, go to the project on vercel.com, then *Settings → Domains*.

**Option B: GitHub + Vercel (easy to update later)**
1. Create a GitHub repository and upload the contents of `bouquet/` (or only `web/`).
2. On <https://vercel.com/new>, import the repository.
3. If you uploaded the whole project, set **Root Directory** to `web`. Set **Framework Preset** to *Other* and leave the build command empty. Then click **Deploy**.
4. Every time you edit `index.html` on GitHub, Vercel redeploys automatically.

Netlify Drop (<https://app.netlify.com/drop>, drag the `web` folder) and GitHub Pages work too.

Tips:
* Before sending the link, open it yourself on a phone and on a laptop.
* Send it when she can watch the whole opening somewhere quiet. Turning the screen brightness up helps.
* `…/?video` forces the pre-rendered film, in case her device struggles.
* To try it on your own computer first, run `npx serve web` and open the address it prints.

---

## How it works (short version)

| Piece | What it does |
|---|---|
| **Geometry** | Every petal is its own curved, cupped surface with organic wobble and ruffled edges. Roses have 26–33 petals on a golden-angle spiral that open from the outside in. Each hydrangea head has 230–340 four- and five-petal florets. The baby's breath is made of branching sprays, the eucalyptus has paired leaves on arching stems, the greenery is lance-shaped leaves, and the stems are spiralled and hand-tied. The silk bow is built from swept ribbon strips. |
| **Materials** | Cycles uses Principled BSDF with subsurface scattering, sheen and real thickness (Solidify) on the petals. The leaves have generated vein textures and normal maps, and the ribbon is anisotropic silk. In the browser, physical materials with sheen and a back-light translucency term make the petals glow when lit from behind. |
| **Light** | A warm key light from the upper left, a pink fill and a golden rim, plus a spotlight for the first rose, soft volumetric beams, drifting dust and a light that sweeps across during the reveal. |
| **Camera** | The same shots are used in Blender and on the web: darkness, a slow push-in to the rose, a mid shot while the bouquet blooms, then a pull back as the bouquet turns. |
| **Web** | Three.js with ACES tone mapping, soft shadows, bloom, depth of field, film grain and a vignette. It lowers its quality automatically on slower phones and uses instancing for the thousands of florets. |
