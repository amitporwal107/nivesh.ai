package ai.nivesh.app.ui.markets;

import ai.nivesh.app.data.repo.MarketsRepository;
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
public final class MarketsViewModel_Factory implements Factory<MarketsViewModel> {
  private final Provider<MarketsRepository> repoProvider;

  public MarketsViewModel_Factory(Provider<MarketsRepository> repoProvider) {
    this.repoProvider = repoProvider;
  }

  @Override
  public MarketsViewModel get() {
    return newInstance(repoProvider.get());
  }

  public static MarketsViewModel_Factory create(Provider<MarketsRepository> repoProvider) {
    return new MarketsViewModel_Factory(repoProvider);
  }

  public static MarketsViewModel newInstance(MarketsRepository repo) {
    return new MarketsViewModel(repo);
  }
}
