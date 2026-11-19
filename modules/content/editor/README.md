# The content editor

The WYSIWYG for an entry's body: [Tiptap](https://tiptap.dev) on ProseMirror, both MIT.
Built once into `../src/nest_content/static/editor/editor.js`, which is committed, so Nest
needs no Node to run. To change it:

```sh
npm ci            # the exact versions of package-lock.json
npm run build     # writes ../src/nest_content/static/editor/editor.js
```

`src/editor.js` takes over `<textarea data-editor>` (the form still posts the textarea) and
`<input data-media-pick>` (the featured image). It writes no style into the page, as the
site's security policy allows none: Tiptap's CSS is in `../src/nest_content/static/editor/editor.css`.
