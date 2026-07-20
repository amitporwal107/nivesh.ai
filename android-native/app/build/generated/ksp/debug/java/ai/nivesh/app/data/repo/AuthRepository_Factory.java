package ai.nivesh.app.data.repo;

import ai.nivesh.app.auth.GoogleSignInClient;
import ai.nivesh.app.auth.TokenStore;
import ai.nivesh.app.data.api.NiveshApi;
import dagger.internal.DaggerGenerated;
import dagger.internal.Factory;
import dagger.internal.QualifierMetadata;
import dagger.internal.ScopeMetadata;
import javax.annotation.processing.Generated;
import javax.inject.Provider;

@ScopeMetadata("javax.inject.Singleton")
@QualifierMetadata
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
public final class AuthRepository_Factory implements Factory<AuthRepository> {
  private final Provider<NiveshApi> apiProvider;

  private final Provider<TokenStore> tokenStoreProvider;

  private final Provider<GoogleSignInClient> googleSignInProvider;

  public AuthRepository_Factory(Provider<NiveshApi> apiProvider,
      Provider<TokenStore> tokenStoreProvider, Provider<GoogleSignInClient> googleSignInProvider) {
    this.apiProvider = apiProvider;
    this.tokenStoreProvider = tokenStoreProvider;
    this.googleSignInProvider = googleSignInProvider;
  }

  @Override
  public AuthRepository get() {
    return newInstance(apiProvider.get(), tokenStoreProvider.get(), googleSignInProvider.get());
  }

  public static AuthRepository_Factory create(Provider<NiveshApi> apiProvider,
      Provider<TokenStore> tokenStoreProvider, Provider<GoogleSignInClient> googleSignInProvider) {
    return new AuthRepository_Factory(apiProvider, tokenStoreProvider, googleSignInProvider);
  }

  public static AuthRepository newInstance(NiveshApi api, TokenStore tokenStore,
      GoogleSignInClient googleSignIn) {
    return new AuthRepository(api, tokenStore, googleSignIn);
  }
}
