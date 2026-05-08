# Getting Started with Create React App

This project was bootstrapped with [Create React App](https://github.com/facebook/create-react-app).

## Mobile (iOS + Android via Capacitor)

The web app is wrapped as a native mobile app using [Capacitor](https://capacitorjs.com).

- **App ID**: `ai.nivesh.app`
- **Display name**: `nivesh.ai`
- **Web layer**: existing CRA build under `build/` is bundled into the native shell
- **Native projects**: `android/` (Android Studio) and `ios/` (Xcode)

### Prerequisites

- **Android**: Android Studio + Android SDK 33+, JDK 17. Open `android/` in Android Studio for first run, or use `yarn cap:run:android` with a connected device/emulator.
- **iOS**: macOS with Xcode 15+, CocoaPods (`sudo gem install cocoapods`). Run `cd ios/App && pod install` after the first sync (Capacitor skips this on Linux). Then open `ios/App/App.xcworkspace`.

### Common scripts

```bash
yarn cap:sync           # rebuild web + sync into both native projects
yarn cap:android        # build, sync, open in Android Studio
yarn cap:ios            # build, sync, open in Xcode (macOS only)
yarn cap:run:android    # build, sync, run on attached Android device/emulator
yarn cap:run:ios        # build, sync, run on attached iOS simulator (macOS only)
```

### Backend / API notes

The mobile app loads the web bundle from a local origin inside the WebView, then calls `REACT_APP_BACKEND_URL` over HTTPS. Two things must be true on the backend:

1. **CORS**: the API allowlist must include the WebView origins
   - Android: `https://localhost`
   - iOS: `capacitor://localhost`
2. **Auth cookies**: any `Set-Cookie` returned by the API must use `SameSite=None; Secure` for the WebView to keep them across requests.

### Known caveat: Google OAuth

`@react-oauth/google` opens an embedded Google sign-in flow. Google blocks this in WebViews, so it will fail in the wrapped app. To fix, swap to the system browser via `@capacitor/browser` (or use [`@codetrix-studio/capacitor-google-auth`](https://github.com/CodetrixStudio/CapacitorGoogleAuth)) and configure the OAuth client to allow the `ai.nivesh.app` redirect scheme. This is a follow-up — not required to install/run the app, only to log in via Google on device.

### After editing web code

Native projects ship the contents of `build/` baked in. Re-run `yarn cap:sync` (or any `cap:*` script) after changes — hot reload from the dev server requires extra config and is off by default.



## Available Scripts

In the project directory, you can run:

### `npm start`

Runs the app in the development mode.\
Open [http://localhost:3000](http://localhost:3000) to view it in your browser.

The page will reload when you make changes.\
You may also see any lint errors in the console.

### `npm test`

Launches the test runner in the interactive watch mode.\
See the section about [running tests](https://facebook.github.io/create-react-app/docs/running-tests) for more information.

### `npm run build`

Builds the app for production to the `build` folder.\
It correctly bundles React in production mode and optimizes the build for the best performance.

The build is minified and the filenames include the hashes.\
Your app is ready to be deployed!

See the section about [deployment](https://facebook.github.io/create-react-app/docs/deployment) for more information.

### `npm run eject`

**Note: this is a one-way operation. Once you `eject`, you can't go back!**

If you aren't satisfied with the build tool and configuration choices, you can `eject` at any time. This command will remove the single build dependency from your project.

Instead, it will copy all the configuration files and the transitive dependencies (webpack, Babel, ESLint, etc) right into your project so you have full control over them. All of the commands except `eject` will still work, but they will point to the copied scripts so you can tweak them. At this point you're on your own.

You don't have to ever use `eject`. The curated feature set is suitable for small and middle deployments, and you shouldn't feel obligated to use this feature. However we understand that this tool wouldn't be useful if you couldn't customize it when you are ready for it.

## Learn More

You can learn more in the [Create React App documentation](https://facebook.github.io/create-react-app/docs/getting-started).

To learn React, check out the [React documentation](https://reactjs.org/).

### Code Splitting

This section has moved here: [https://facebook.github.io/create-react-app/docs/code-splitting](https://facebook.github.io/create-react-app/docs/code-splitting)

### Analyzing the Bundle Size

This section has moved here: [https://facebook.github.io/create-react-app/docs/analyzing-the-bundle-size](https://facebook.github.io/create-react-app/docs/analyzing-the-bundle-size)

### Making a Progressive Web App

This section has moved here: [https://facebook.github.io/create-react-app/docs/making-a-progressive-web-app](https://facebook.github.io/create-react-app/docs/making-a-progressive-web-app)

### Advanced Configuration

This section has moved here: [https://facebook.github.io/create-react-app/docs/advanced-configuration](https://facebook.github.io/create-react-app/docs/advanced-configuration)

### Deployment

This section has moved here: [https://facebook.github.io/create-react-app/docs/deployment](https://facebook.github.io/create-react-app/docs/deployment)

### `npm run build` fails to minify

This section has moved here: [https://facebook.github.io/create-react-app/docs/troubleshooting#npm-run-build-fails-to-minify](https://facebook.github.io/create-react-app/docs/troubleshooting#npm-run-build-fails-to-minify)
