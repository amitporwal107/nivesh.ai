package ai.nivesh.app.ui;

import ai.nivesh.app.data.repo.AuthRepository;
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
public final class RootViewModel_Factory implements Factory<RootViewModel> {
  private final Provider<AuthRepository> authRepositoryProvider;

  public RootViewModel_Factory(Provider<AuthRepository> authRepositoryProvider) {
    this.authRepositoryProvider = authRepositoryProvider;
  }

  @Override
  public RootViewModel get() {
    return newInstance(authRepositoryProvider.get());
  }

  public static RootViewModel_Factory create(Provider<AuthRepository> authRepositoryProvider) {
    return new RootViewModel_Factory(authRepositoryProvider);
  }

  public static RootViewModel newInstance(AuthRepository authRepository) {
    return new RootViewModel(authRepository);
  }
}
