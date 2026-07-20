package ai.nivesh.app.ui.recommendations;

import ai.nivesh.app.data.repo.PlansRepository;
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
public final class RecommendationsViewModel_Factory implements Factory<RecommendationsViewModel> {
  private final Provider<PlansRepository> repoProvider;

  public RecommendationsViewModel_Factory(Provider<PlansRepository> repoProvider) {
    this.repoProvider = repoProvider;
  }

  @Override
  public RecommendationsViewModel get() {
    return newInstance(repoProvider.get());
  }

  public static RecommendationsViewModel_Factory create(Provider<PlansRepository> repoProvider) {
    return new RecommendationsViewModel_Factory(repoProvider);
  }

  public static RecommendationsViewModel newInstance(PlansRepository repo) {
    return new RecommendationsViewModel(repo);
  }
}
