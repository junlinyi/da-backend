// firebaseConfig.js
import { initializeApp } from "firebase/app";
import { initializeAuth, getReactNativePersistence } from "firebase/auth";
import AsyncStorage from "@react-native-async-storage/async-storage";

const firebaseConfig = {
  apiKey: "AIzaSyBWPk8w9mbx-wdJc2dJVC8SbpydGAsJukE",
  authDomain: "dating-app-backend-221df.firebaseapp.com",
  projectId: "dating-app-backend-221df",
  storageBucket: "dating-app-backend-221df.firebaseapp.com",
  messagingSenderId: "892017633280",
  appId: "1:892017633280:web:666bb085507ef8e89fd0e5",
  measurementId: "G-3MXBRQM8WJ"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);

// Initialize Auth with AsyncStorage persistence
const auth = initializeAuth(app, {
  persistence: getReactNativePersistence(AsyncStorage)
});

export { app, auth }; 