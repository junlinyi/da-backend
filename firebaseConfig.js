// firebaseConfig.js
// Import the functions you need from the SDKs you need
import { initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";
// TODO: Add SDKs for Firebase products that you want to use
// https://firebase.google.com/docs/web/setup#available-libraries
// For Firebase JS SDK v7.20.0 and later, measurementId is optional
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
const auth = getAuth(app);

export { app, auth }; 