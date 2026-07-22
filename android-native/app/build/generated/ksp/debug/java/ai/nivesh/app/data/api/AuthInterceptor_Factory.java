package ai.nivesh.app.data.api;

import ai.nivesh.app.auth.TokenStore;
import dagger.internal.DaggerGenerated;
import dagger.internal.Factory;
import dagger.internal.QualifierMetadata;
import dagger.internal.ScopeMetadata;
import javax.annotation.processing.Generated;
import javax.inject.Provider;

@ScopeMetadata
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
public final class AuthInterceptor_Factory implements Factory<AuthInterceptor> {
  private final Provider<TokenStore> tokenStoreProvider;

  public AuthInterceptor_Factory(Provider<TokenStore> tokenStoreProvider) {
    this.tokenStoreProvider = tokenStoreProvider;
  }

  @Override
  public AuthInterceptor get() {
    return newInstance(tokenStoreProvider.get());
  }

  public static AuthInterceptor_Factory create(Provider<TokenStore> tokenStoreProvider) {
    return new AuthInterceptor_Factory(tokenStoreProvider);
  }

  public static AuthInterceptor newInstance(TokenStore tokenStore) {
    return new AuthInterceptor(tokenStore);
  }
}
