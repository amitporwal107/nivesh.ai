package ai.nivesh.app.auth;

import android.content.Context;
import dagger.internal.DaggerGenerated;
import dagger.internal.Factory;
import dagger.internal.QualifierMetadata;
import dagger.internal.ScopeMetadata;
import javax.annotation.processing.Generated;
import javax.inject.Provider;

@ScopeMetadata("javax.inject.Singleton")
@QualifierMetadata("dagger.hilt.android.qualifiers.ApplicationContext")
@DaggerGenerated
@Generated(
    value = "dagger.internal.codegen.ComponentProcessor",
    comments = "https://dagger.dev"
)
@SuppressWarnings({
    "unchecked",
    "rawtypes",
    "KotlinInternal",
    "KotlinInternalInJava"
})
public final class GoogleSignInClient_Factory implements Factory<GoogleSignInClient> {
  private final Provider<Context> appContextProvider;

  public GoogleSignInClient_Factory(Provider<Context> appContextProvider) {
    this.appContextProvider = appContextProvider;
  }

  @Override
  public GoogleSignInClient get() {
    return newInstance(appContextProvider.get());
  }

  public static GoogleSignInClient_Factory create(Provider<Context> appContextProvider) {
    return new GoogleSignInClient_Factory(appContextProvider);
  }

  public static GoogleSignInClient newInstance(Context appContext) {
    return new GoogleSignInClient(appContext);
  }
}
