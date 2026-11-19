plugins {
    id("com.android.application")
    id("com.chaquo.python")
}
android {
    namespace = "com.group7.eventtodo"
    compileSdk { version = release(37) { minorApiLevel = 0 } }
    defaultConfig {
        applicationId = "com.group7.eventtodo"
        minSdk = 28
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0-mvp"
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlin { compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) } }
    buildTypes { release { isMinifyEnabled = false } }
    signingConfigs {
        getByName("debug") {
            val localKey = rootProject.file("build/mobile-debug.keystore")
            if (localKey.exists()) {
                storeFile = localKey
                storePassword = "android"
                keyAlias = "androiddebugkey"
                keyPassword = "android"
            }
        }
    }
}
chaquopy {
    defaultConfig {
        version = "3.12"
        buildPython(providers.environmentVariable("EVENT_TODO_BUILD_PYTHON").getOrElse("python3"))
    }
}
dependencies {
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("com.google.mlkit:text-recognition-chinese:16.0.1")
    implementation("com.google.mlkit:text-recognition:16.0.1")
}
